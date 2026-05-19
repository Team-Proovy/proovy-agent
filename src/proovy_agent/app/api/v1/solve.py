"""문제 풀이 API 엔드포인트."""

import asyncio
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
            await get_graph().ainvoke(state)
        except Exception:
            logger.exception("solve 실행 중 오류 발생")
            await emitter.emit("error", {"message": "풀이 중 오류가 발생했습니다."})
        finally:
            await emitter.close()
            current_emitter.reset(token)

    task: asyncio.Task[None] = asyncio.create_task(_run())
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return EventSourceResponse(emitter.stream())
