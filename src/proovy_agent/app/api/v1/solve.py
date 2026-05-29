"""문제 풀이 API 엔드포인트."""

import asyncio
from collections.abc import AsyncGenerator
import logging
import uuid

from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from sse_starlette.sse import EventSourceResponse

from proovy_agent.app.schemas.solve import SolveRequest
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.emitter import SSEEmitter
from proovy_agent.graph.builder import get_graph
from proovy_agent.graph.state import ProovyState

router = APIRouter()
logger = logging.getLogger(__name__)

# fire-and-forget 태스크 참조 유지 (GC 방지)
_active_tasks: set[asyncio.Task[None]] = set()

# SSE ping 간격(초). sse-starlette 기본값(15)과 동일하나, 설계 §6.1 계약을 코드로
# 명시하고 라이브러리 기본값 변경 시 회귀를 막기 위해 고정한다. 배포 LB/프록시의
# idle 타임아웃이 15초보다 짧으면 이 값을 줄여 튜닝한다 (인프라 설정은 배포 트랙 확인).
_SSE_PING_INTERVAL: int = 15


def _build_initial_state(request: SolveRequest) -> ProovyState:
    thread_id = request.thread_id or str(uuid.uuid4())
    return ProovyState(
        raw_input={"problem": request.problem},
        user_id=request.user_id,
        thread_id=thread_id,
        messages=[HumanMessage(content=request.problem)],
    )


@router.post("/solve", response_class=EventSourceResponse)
async def solve_endpoint(request: SolveRequest) -> EventSourceResponse:
    """수학 문제를 SSE로 스트리밍하며 풀이합니다."""
    emitter = SSEEmitter()
    state = _build_initial_state(request)

    async def _run() -> None:
        token = current_emitter.set(emitter)
        try:
            # 체크포인트 키를 user_id로 네임스페이스해 타 사용자 thread_id 접근을 차단.
            # user_id 인증 자체는 상위 게이트웨이/BFF 책임 (여기선 신뢰 가정).
            checkpoint_thread_id = f"{state.user_id}:{state.thread_id}"
            await get_graph().ainvoke(
                state,
                config={"configurable": {"thread_id": checkpoint_thread_id}},
            )
        except asyncio.CancelledError:
            logger.info("클라이언트 연결 종료로 solve 태스크가 취소되었습니다.")
        except Exception as exc:
            logger.exception("solve 실행 중 오류 발생")
            if not getattr(exc, "sse_emitted", False):
                await emitter.emit("error", {"message": "풀이 중 오류가 발생했습니다."})
        finally:
            await emitter.close()
            current_emitter.reset(token)

    # 그래프 태스크는 SSE 연결과 독립적으로 실행 — disconnect 시에도 풀이가 완료됨
    task: asyncio.Task[None] = asyncio.create_task(_run())
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    async def _stream() -> AsyncGenerator:
        async for event in emitter.stream():
            yield event

    # 유휴 구간 프록시 idle 타임아웃 방지 + SSE 연결 끊김 시 스트림 종료.
    # (그래프 풀이는 별도 fire-and-forget 태스크라 disconnect로 취소되지 않음 — _run 참고)
    return EventSourceResponse(_stream(), ping=_SSE_PING_INTERVAL)
