"""SSE 이미터/emit 컨텍스트 ContextVar."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proovy_agent.common.sse.emitter import SSEEmitter

# CoreSolver 노드가 실행 전에 set(), tool들이 get()으로 참조
current_emitter: ContextVar[SSEEmitter | None] = ContextVar("current_emitter", default=None)


@dataclass(frozen=True)
class EmitContext:
    """현재 emit의 envelope 메타(node/step_idx)를 운반한다.

    PlanExecutor가 step마다 set/reset하며, 노드/도구 코드는 emit 시점에 인자를
    넘기지 않아도 emitter가 이 컨텍스트에서 node/step_idx를 자동 주입한다.
    asyncio.Task별로 독립이라 병렬 브랜치(video/pdf)는 자동 분리된다.
    """

    node: str = ""
    step_idx: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# PlanExecutor가 step 진입 시 set(), 노드/도구 emit이 get()으로 참조.
# 미설정 시 None — emitter가 기본 EmitContext()로 폴백한다 (ContextVar 기본값에
# 가변 객체를 두지 않기 위함).
current_emit_context: ContextVar[EmitContext | None] = ContextVar(
    "current_emit_context", default=None
)
