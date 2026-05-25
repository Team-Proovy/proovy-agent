"""SSE 이벤트 타입 정의.

11종 EventType과 Pydantic discriminated union으로 envelope/payload 분리.
emitter/호출부 전환은 후속 이슈에서.
"""

from datetime import UTC, datetime
import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from proovy_agent.graph.state import CreditEntry, PlanStep

# ────────────────────────────────────────────────────────────────────────────
# Literal 타입
# ────────────────────────────────────────────────────────────────────────────

EventType = Literal[
    "page_start",
    "solve_progress",
    "token",
    "tool_start",
    "tool_result",
    "image_placeholder",
    "image_result",
    "node_result",
    "credit_settled",
    "error",
    "done",
]

ErrorCode = Literal[
    "internal_error",
    "tool_error",
    "model_error",
    "credit_exhausted",
    "timeout",
    "invalid_input",
]


# ────────────────────────────────────────────────────────────────────────────
# Payload 모델 — envelope에 있는 thread_id/seq/ts/step_idx/node는 제외
# ────────────────────────────────────────────────────────────────────────────


# Lifecycle ─────────────────────────────────────────────────────────────────


class PageStartPayload(BaseModel):
    plan: list[PlanStep]
    selected_model: Literal["flash", "sonnet", "opus"]
    difficulty: Literal["easy", "medium", "hard"]
    route: Literal["general_chat", "math_task"]
    use_page: bool


class CreditSettledPayload(BaseModel):
    reserved: float
    actual: float
    refunded: float
    log: list[CreditEntry]


class ErrorPayload(BaseModel):
    code: ErrorCode = "internal_error"
    message: str
    recoverable: bool = False
    tool_call_id: str | None = None


class DonePayload(BaseModel):
    final: Literal[True] = True


# Progress ──────────────────────────────────────────────────────────────────


class SolveProgressPayload(BaseModel):
    text: str
    iteration: int = 0
    phase: Literal["verify", "explain"] = "verify"


class NodeResultPayload(BaseModel):
    status: Literal["done", "error"]
    duration_ms: int
    error_code: str | None = None


# Streaming ─────────────────────────────────────────────────────────────────


class TokenPayload(BaseModel):
    delta: str
    final: bool = False


# Tool & Media ──────────────────────────────────────────────────────────────


class ToolStartPayload(BaseModel):
    name: str
    label: str
    tool_call_id: str = ""


class ToolResultPayload(BaseModel):
    name: str
    tool_call_id: str = ""
    output: str
    success: bool


class ImagePlaceholderPayload(BaseModel):
    placeholder_id: str
    label: str


class ImageResultPayload(BaseModel):
    placeholder_id: str
    url: str
    width: int
    height: int
    mime_type: str = "image/png"


# ────────────────────────────────────────────────────────────────────────────
# Envelope — 모든 이벤트 공통 메타 + type discriminator
# ────────────────────────────────────────────────────────────────────────────


class _EnvelopeBase(BaseModel):
    thread_id: str
    seq: int
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step_idx: int = 0
    node: str = ""


class PageStartEvent(_EnvelopeBase):
    type: Literal["page_start"] = "page_start"
    payload: PageStartPayload


class SolveProgressEvent(_EnvelopeBase):
    type: Literal["solve_progress"] = "solve_progress"
    payload: SolveProgressPayload


class TokenEvent(_EnvelopeBase):
    type: Literal["token"] = "token"
    payload: TokenPayload


class ToolStartEvent(_EnvelopeBase):
    type: Literal["tool_start"] = "tool_start"
    payload: ToolStartPayload


class ToolResultEvent(_EnvelopeBase):
    type: Literal["tool_result"] = "tool_result"
    payload: ToolResultPayload


class ImagePlaceholderEvent(_EnvelopeBase):
    type: Literal["image_placeholder"] = "image_placeholder"
    payload: ImagePlaceholderPayload


class ImageResultEvent(_EnvelopeBase):
    type: Literal["image_result"] = "image_result"
    payload: ImageResultPayload


class NodeResultEvent(_EnvelopeBase):
    type: Literal["node_result"] = "node_result"
    payload: NodeResultPayload


class CreditSettledEvent(_EnvelopeBase):
    type: Literal["credit_settled"] = "credit_settled"
    payload: CreditSettledPayload


class ErrorEvent(_EnvelopeBase):
    type: Literal["error"] = "error"
    payload: ErrorPayload


class DoneEvent(_EnvelopeBase):
    type: Literal["done"] = "done"
    payload: DonePayload


SSEEvent = Annotated[
    PageStartEvent
    | SolveProgressEvent
    | TokenEvent
    | ToolStartEvent
    | ToolResultEvent
    | ImagePlaceholderEvent
    | ImageResultEvent
    | NodeResultEvent
    | CreditSettledEvent
    | ErrorEvent
    | DoneEvent,
    Field(discriminator="type"),
]


def to_sse(event: _EnvelopeBase) -> dict[str, str]:
    """sse-starlette ServerSentEvent 호환 dict로 직렬화한다."""
    return {
        "event": event.type,  # type: ignore[attr-defined]
        "id": f"{event.thread_id}:{event.seq}",
        "data": event.model_dump_json(),
    }


# ────────────────────────────────────────────────────────────────────────────
# Legacy — SSEEmitter 전환(후속 이슈) 전까지 임시 보존. 후속 이슈에서 삭제.
# ────────────────────────────────────────────────────────────────────────────


class LegacySSEEvent(BaseModel):
    """deprecated: 후속 이슈에서 SSEEmitter 전환과 함께 제거 예정."""

    event: EventType
    data: dict

    def to_sse(self) -> dict:
        return {"event": self.event, "data": json.dumps(self.data, ensure_ascii=False)}
