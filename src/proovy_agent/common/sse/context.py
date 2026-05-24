"""Context variable for the current SSE emitter."""

from contextvars import ContextVar

from proovy_agent.common.sse.emitter import SSEEmitter

# CoreSolver 노드가 실행 전에 set(), tool들이 get()으로 참조
current_emitter: ContextVar[SSEEmitter | None] = ContextVar("current_emitter", default=None)
