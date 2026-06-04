"""SSE 스트리밍 엔드포인트 공유 실행 헬퍼.

`/solve`(내부 envelope)와 `/stream/v2`(백엔드 vocab)가 동일한 그래프 실행·생명주기
로직을 공유한다 — 출력 직렬화만 엔드포인트별로 다르다. 그래프 태스크는 SSE 연결과
독립적으로 실행돼 클라이언트 disconnect 시에도 풀이가 완료된다.

`graph`는 호출부(엔드포인트 모듈)에서 `get_graph()`로 조회해 주입한다. 이렇게 하면
테스트가 각 엔드포인트 모듈의 `get_graph`를 patch하는 기존 방식이 그대로 유지된다.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from langgraph.graph.state import CompiledStateGraph

from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.emitter import SSEEmitter
from proovy_agent.common.sse.events import DonePayload, ErrorPayload
from proovy_agent.graph.runtime import (
    ActiveHoldTrackingCreditLedgerClient,
    current_credit_ledger_client,
    current_video_job_client,
    track_active_credit_hold,
)
from proovy_agent.graph.state import ProovyState

if TYPE_CHECKING:
    from proovy_agent.features.credits.service import CreditLedgerClient
    from proovy_agent.features.video.jobs import VideoJobClient

logger = logging.getLogger(__name__)

# SSE ping 간격(초). sse-starlette 기본값(15)과 동일하나, 설계 §6.1 계약을 코드로
# 명시하고 라이브러리 기본값 변경 시 회귀를 막기 위해 고정한다. 배포 LB/프록시의
# idle 타임아웃이 15초보다 짧으면 이 값을 줄여 튜닝한다 (인프라 설정은 배포 트랙 확인).
SSE_PING_INTERVAL: int = 15

# fire-and-forget 태스크 참조 유지 (GC 방지)
_active_tasks: set[asyncio.Task[None]] = set()


async def _release_active_credit_hold(
    ledger: ActiveHoldTrackingCreditLedgerClient | None,
    user_id: str,
) -> None:
    if ledger is None or ledger.active_hold_id is None:
        return

    hold_id = ledger.active_hold_id
    try:
        await ledger.release_active_hold(user_id)
    except Exception:
        logger.exception("그래프 실패 후 pending credit hold release 실패: hold_id=%s", hold_id)


async def cancel_active_graph_tasks() -> None:
    """Cancel and await in-flight graph tasks before shared clients close."""
    current_task = asyncio.current_task()
    tasks = [task for task in _active_tasks if task is not current_task and not task.done()]
    if not tasks:
        return

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def start_graph_task(
    state: ProovyState,
    graph: CompiledStateGraph,
    *,
    credit_ledger_client: "CreditLedgerClient | None" = None,
    video_job_client: "VideoJobClient | None" = None,
) -> SSEEmitter:
    """그래프 풀이를 fire-and-forget 태스크로 시작하고 이벤트 수집용 emitter를 반환한다.

    호출부는 반환된 emitter의 `stream()`으로 SSE 응답을 만든다(직렬화기 선택은 호출부
    책임). 그래프 태스크는 SSE 연결과 독립적이라 disconnect 시에도 끝까지 실행된다.
    """
    emitter = SSEEmitter(thread_id=state.thread_id)
    tracked_credit_ledger_client = track_active_credit_hold(credit_ledger_client)

    async def _run() -> None:
        emitter_token = current_emitter.set(emitter)
        credit_token = current_credit_ledger_client.set(tracked_credit_ledger_client)
        video_token = current_video_job_client.set(video_job_client)
        try:
            # 체크포인트 키를 user_id로 네임스페이스해 타 사용자 thread_id 접근을 차단.
            # user_id 인증 자체는 상위 게이트웨이/BFF 책임 (여기선 신뢰 가정).
            checkpoint_thread_id = f"{state.user_id}:{state.thread_id}"
            await graph.ainvoke(
                state,
                config={"configurable": {"thread_id": checkpoint_thread_id}},
            )
            # 정상 완료 신호 — 클라이언트가 EventSource onerror에 의존하지 않게 한다
            await emitter.emit(DonePayload())
        except asyncio.CancelledError:
            # 클라이언트 연결 종료 — done/error 둘 다 보내지 않는다
            await _release_active_credit_hold(tracked_credit_ledger_client, state.user_id)
            logger.info("클라이언트 연결 종료로 solve 태스크가 취소되었습니다.")
        except Exception as exc:
            logger.exception("solve 실행 중 오류 발생")
            await _release_active_credit_hold(tracked_credit_ledger_client, state.user_id)
            if not getattr(exc, "sse_emitted", False):
                await emitter.emit(ErrorPayload(message="풀이 중 오류가 발생했습니다."))
        finally:
            await emitter.close()
            current_video_job_client.reset(video_token)
            current_credit_ledger_client.reset(credit_token)
            current_emitter.reset(emitter_token)

    # 그래프 태스크는 SSE 연결과 독립적으로 실행 — disconnect 시에도 풀이가 완료됨
    task: asyncio.Task[None] = asyncio.create_task(_run())
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return emitter
