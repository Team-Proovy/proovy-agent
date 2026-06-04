"""SSE 이벤트 타입 정의.

11종 EventType과 Pydantic discriminated union으로 envelope/payload 분리.
"""

from datetime import UTC, datetime
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
# SSE wire DTO — SSE 레이어가 소유하는 슬림 모델
# graph.state(PlanStep/CreditEntry)에 직접 의존하지 않도록 분리해, graph 내부
# 모델 변경이 SSE wire 포맷에 자동 전파되는 결합을 끊는다. from_attributes로
# graph 모델 인스턴스를 변환 없이 그대로 받아 검증한다(생산지점 수정 불필요).
# ────────────────────────────────────────────────────────────────────────────


class PlanStepView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: Literal["solve", "video", "pdf"]
    description: str
    status: Literal["pending", "running", "done", "error"] = "pending"


class CreditEntryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node: str
    action: str
    model: str | None = None
    cost: float


# ────────────────────────────────────────────────────────────────────────────
# Payload 모델 — envelope에 있는 thread_id/seq/ts/step_idx/node는 제외
# ────────────────────────────────────────────────────────────────────────────


# Lifecycle ─────────────────────────────────────────────────────────────────


class PageStartPayload(BaseModel):
    plan: list[PlanStepView]
    selected_model: Literal["flash", "sonnet", "opus"]
    difficulty: Literal["easy", "medium", "hard"]
    route: Literal["general_chat", "math_task"]
    use_page: bool


class CreditSettledPayload(BaseModel):
    actual: float  # 이번 턴 실제 소비 — 항상 신뢰 가능
    log: list[CreditEntryView]
    # 예약(reservation) 흐름 미구현 — 선점 노드 도입 전까지 None. 프론트는 actual만 신뢰.
    reserved: float | None = None
    refunded: float | None = None


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


def to_sse(event: SSEEvent) -> dict[str, str]:
    """sse-starlette ServerSentEvent 호환 dict로 직렬화한다."""
    return {
        "event": event.type,
        "id": f"{event.thread_id}:{event.seq}",
        "data": event.model_dump_json(),
    }


def to_stream_v2(event: SSEEvent) -> dict[str, str] | None:
    """백엔드(Proovy-server) `/stream/v2` 계약으로 변환한다.

    백엔드는 토큰 증분(`llm.token.delta`의 `delta`)만 모아 최종 메시지로 저장하고,
    종료는 `run.completed`/`run.failed`로 감지하며, 어느 이벤트든 `data.thread_id`로
    첫 턴 threadId를 영속화한다. 그 외 내부 이벤트(page_start/tool_*/progress 등)는
    백엔드가 소비하지 않으므로 None으로 drop한다 (envelope 설계는 /solve에서 유지).

    SSE `id`는 싣지 않는다. 백엔드는 서버-투-서버 WebClient Flux로 소비하며
    `Last-Event-ID` 재연결을 쓰지 않고, 내부 이벤트 drop으로 seq가 불연속이라 id를
    실으면 소비자가 gap을 오탐할 수 있다. 재연결/replay는 백엔드 durable store 관할.
    """
    if isinstance(event, TokenEvent):
        name = "llm.token.delta"
        data = {"delta": event.payload.delta, "thread_id": event.thread_id}
    elif isinstance(event, DoneEvent):
        name = "run.completed"
        data = {"thread_id": event.thread_id}
    elif isinstance(event, ErrorEvent):
        name = "run.failed"
        data = {"message": event.payload.message, "thread_id": event.thread_id}
    else:
        return None
    return {
        "event": name,
        "data": json.dumps(data, ensure_ascii=False),
    }
