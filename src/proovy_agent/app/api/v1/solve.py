"""문제 풀이 API 엔드포인트."""

import uuid

from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from sse_starlette.sse import EventSourceResponse

from proovy_agent.app.api._runner import SSE_PING_INTERVAL, start_graph_task
from proovy_agent.app.schemas.solve import SolveRequest
from proovy_agent.graph.builder import get_graph
from proovy_agent.graph.state import ProovyState

router = APIRouter()

# 모듈 로컬 별칭 — 엔드포인트 가독성 + ping 계약 테스트 호환.
# 실제 값/근거는 _runner.SSE_PING_INTERVAL 참고.
_SSE_PING_INTERVAL = SSE_PING_INTERVAL


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
    """수학 문제를 SSE로 스트리밍하며 풀이합니다.

    그래프 실행은 _runner.start_graph_task가 담당하며(SSE 연결과 독립된 fire-and-forget
    태스크), 본 엔드포인트는 내부 envelope 포맷(to_sse)으로 스트리밍한다. 백엔드 연동용
    포맷은 /stream/v2 참고.
    """
    state = _build_initial_state(request)
    emitter = start_graph_task(state, get_graph())
    # 유휴 구간 프록시 idle 타임아웃 방지 + SSE 연결 끊김 시 스트림 종료.
    return EventSourceResponse(emitter.stream(), ping=_SSE_PING_INTERVAL)
