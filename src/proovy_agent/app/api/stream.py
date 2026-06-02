"""백엔드(Proovy-server) 연동용 SSE 스트리밍 엔드포인트.

- `POST /stream/v2` — 백엔드 `ProovyAiRequest`(StreamInput) 계약. 내부적으로는 `/solve`와
  동일한 그래프를 실행하되(`start_graph_task`), 출력만 백엔드 vocab으로 직렬화한다
  (`to_stream_v2`: token→`llm.token.delta`, done→`run.completed`, error→`run.failed`).
- `GET /health` — 백엔드가 스트리밍 전 사전 체크하는 헬스 엔드포인트.

배포 ingress가 `https://.../ai/*`를 앱 `/*`로 매핑한다고 가정한다(prefix 없이 등록).
"""

import uuid

from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from sse_starlette.sse import EventSourceResponse

from proovy_agent.app.api._runner import SSE_PING_INTERVAL, start_graph_task
from proovy_agent.app.schemas.stream import StreamInput
from proovy_agent.common.sse.events import to_stream_v2
from proovy_agent.graph.builder import get_graph
from proovy_agent.graph.state import ProovyState

router = APIRouter()


@router.get("/health", summary="헬스체크 (liveness — 백엔드 사전 연결 확인용)")
async def health() -> dict[str, str]:
    """**liveness 전용** — 프로세스가 요청을 받는지만 확인한다.

    백엔드 `checkProovyAiHealth`는 연결 가능 여부(connection-refused)만 보고 스트리밍을
    시작하므로 본 엔드포인트도 그 계약에 맞춘다. checkpointer/DB/Daytona/그래프 준비
    상태(readiness)는 검사하지 않으며, readiness가 필요해지면 별도 엔드포인트로 분리한다.
    """
    return {"status": "ok"}


def _build_initial_state(payload: StreamInput) -> ProovyState:
    thread_id = payload.thread_id or str(uuid.uuid4())
    return ProovyState(
        raw_input={"problem": payload.message},
        user_id=payload.user_id,
        thread_id=thread_id,
        messages=[HumanMessage(content=payload.message)],
    )


@router.post("/stream/v2", response_class=EventSourceResponse)
async def stream_v2(payload: StreamInput) -> EventSourceResponse:
    """백엔드 계약(`/stream/v2`)으로 문제 풀이를 SSE 스트리밍한다."""
    state = _build_initial_state(payload)
    emitter = start_graph_task(state, get_graph())
    # 백엔드 vocab으로 직렬화 — 내부 전용 이벤트는 to_stream_v2가 None으로 drop
    return EventSourceResponse(emitter.stream(serializer=to_stream_v2), ping=SSE_PING_INTERVAL)
