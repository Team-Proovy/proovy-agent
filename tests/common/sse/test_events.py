"""SSE Payload/Envelope 모델 단위 테스트."""

import json
from typing import get_args

from pydantic import TypeAdapter, ValidationError
import pytest

from proovy_agent.common.sse.events import (
    CreditSettledEvent,
    CreditSettledPayload,
    DoneEvent,
    DonePayload,
    ErrorEvent,
    ErrorPayload,
    EventType,
    ImagePlaceholderPayload,
    ImageResultPayload,
    NodeResultEvent,
    NodeResultPayload,
    PageStartEvent,
    PageStartPayload,
    SolveProgressPayload,
    SSEEvent,
    TokenEvent,
    TokenPayload,
    ToolResultPayload,
    ToolStartPayload,
    to_sse,
    to_stream_v2,
)
from proovy_agent.graph.state import CreditEntry, PlanStep

# ────────────────────────────────────────────────────────────────────────────
# Payload validation
# ────────────────────────────────────────────────────────────────────────────


def test_token_payload_requires_delta() -> None:
    with pytest.raises(ValidationError):
        TokenPayload()  # type: ignore[call-arg]


def test_token_payload_defaults_final_to_false() -> None:
    payload = TokenPayload(delta="안녕")
    assert payload.delta == "안녕"
    assert payload.final is False


def test_done_payload_final_is_locked_true() -> None:
    payload = DonePayload()
    assert payload.final is True

    with pytest.raises(ValidationError):
        DonePayload(final=False)  # type: ignore[arg-type]


def test_error_payload_code_must_be_literal() -> None:
    with pytest.raises(ValidationError):
        ErrorPayload(code="unknown_code", message="x")  # type: ignore[arg-type]


def test_error_payload_default_code_internal_error() -> None:
    payload = ErrorPayload(message="boom")
    assert payload.code == "internal_error"
    assert payload.recoverable is False
    assert payload.tool_call_id is None


def test_solve_progress_payload_phase_literal() -> None:
    SolveProgressPayload(text="x", iteration=1, phase="verify")
    SolveProgressPayload(text="x", iteration=1, phase="explain")
    with pytest.raises(ValidationError):
        SolveProgressPayload(text="x", phase="other")  # type: ignore[arg-type]


def test_node_result_payload_status_literal() -> None:
    NodeResultPayload(status="done", duration_ms=100)
    NodeResultPayload(status="error", duration_ms=100, error_code="X")
    with pytest.raises(ValidationError):
        NodeResultPayload(status="running", duration_ms=100)  # type: ignore[arg-type]


def test_page_start_payload_required_fields() -> None:
    payload = PageStartPayload(
        plan=[PlanStep(action="solve", description="풀이")],
        selected_model="flash",
        difficulty="easy",
        route="math_task",
        use_page=False,
    )
    assert payload.plan[0].action == "solve"
    assert payload.selected_model == "flash"


def test_credit_settled_payload_round_trip() -> None:
    payload = CreditSettledPayload(
        reserved=10.0,
        actual=7.5,
        refunded=2.5,
        log=[CreditEntry(node="core_solver", action="llm", model="flash", cost=7.5)],
    )
    assert payload.refunded == 2.5
    assert payload.log[0].node == "core_solver"


def test_credit_settled_payload_reserved_refunded_optional() -> None:
    """예약 흐름 미구현 시 actual만 필수, reserved/refunded는 None 기본값."""
    payload = CreditSettledPayload(
        actual=5.0,
        log=[CreditEntry(node="core_solver", action="llm", cost=5.0)],
    )
    assert payload.actual == 5.0
    assert payload.reserved is None
    assert payload.refunded is None


def test_tool_payloads_default_tool_call_id() -> None:
    start = ToolStartPayload(name="code_execute", label="실행 중")
    result = ToolResultPayload(name="code_execute", output="42", success=True)
    assert start.tool_call_id == ""
    assert result.tool_call_id == ""


def test_image_result_payload_default_mime_type() -> None:
    payload = ImageResultPayload(
        placeholder_id="ph-1",
        url="https://example.com/x.png",
        width=400,
        height=300,
    )
    assert payload.mime_type == "image/png"


def test_image_placeholder_payload_required_fields() -> None:
    with pytest.raises(ValidationError):
        ImagePlaceholderPayload(placeholder_id="ph-1")  # type: ignore[call-arg]


# ────────────────────────────────────────────────────────────────────────────
# Envelope discriminator
# ────────────────────────────────────────────────────────────────────────────


def test_envelope_default_fields() -> None:
    event = TokenEvent(thread_id="t", seq=0, payload=TokenPayload(delta="x"))
    assert event.type == "token"
    assert event.step_idx == 0
    assert event.node == ""
    assert event.ts is not None


def test_envelope_type_is_locked_per_class() -> None:
    """각 envelope 클래스의 type은 Literal로 고정 — 다른 값 거절."""
    with pytest.raises(ValidationError):
        TokenEvent(
            type="tool_start",  # type: ignore[arg-type]
            thread_id="t",
            seq=0,
            payload=TokenPayload(delta="x"),
        )


def test_envelope_payload_type_is_strict() -> None:
    """TokenEvent에 ToolResultPayload를 넣으면 강제 변환 시도 후 검증 실패."""
    with pytest.raises(ValidationError):
        TokenEvent(
            thread_id="t",
            seq=0,
            payload=ToolResultPayload(  # type: ignore[arg-type]
                name="x", output="y", success=True
            ),
        )


def test_union_discriminator_narrows_on_parse() -> None:
    """type 필드로 union을 좁혀 올바른 envelope 클래스로 역직렬화된다."""
    raw = TokenEvent(
        thread_id="t",
        seq=42,
        payload=TokenPayload(delta="hi"),
    ).model_dump_json()
    adapter: TypeAdapter = TypeAdapter(SSEEvent)
    event = adapter.validate_json(raw)

    assert isinstance(event, TokenEvent)
    assert event.payload.delta == "hi"
    assert event.seq == 42


def test_union_rejects_mismatched_type_payload_combo() -> None:
    """type=token인데 payload는 done 형태 — discriminator 검증 실패."""
    raw = json.dumps(
        {
            "type": "token",
            "thread_id": "t",
            "seq": 0,
            "ts": "2026-05-25T00:00:00Z",
            "step_idx": 0,
            "node": "",
            "payload": {"final": True},
        }
    )
    adapter: TypeAdapter = TypeAdapter(SSEEvent)
    with pytest.raises(ValidationError):
        adapter.validate_json(raw)


def test_union_rejects_unknown_type() -> None:
    raw = json.dumps(
        {
            "type": "unknown_event",
            "thread_id": "t",
            "seq": 0,
            "ts": "2026-05-25T00:00:00Z",
            "payload": {},
        }
    )
    adapter: TypeAdapter = TypeAdapter(SSEEvent)
    with pytest.raises(ValidationError):
        adapter.validate_json(raw)


# ────────────────────────────────────────────────────────────────────────────
# to_sse() 직렬화
# ────────────────────────────────────────────────────────────────────────────


def test_to_sse_returns_event_id_data() -> None:
    event = DoneEvent(thread_id="th-abc", seq=99, payload=DonePayload())
    out = to_sse(event)

    assert out["event"] == "done"
    assert out["id"] == "th-abc:99"
    parsed = json.loads(out["data"])
    assert parsed["type"] == "done"
    assert parsed["thread_id"] == "th-abc"
    assert parsed["seq"] == 99
    assert parsed["payload"] == {"final": True}


def test_to_sse_round_trip_through_union() -> None:
    """to_sse → JSON → TypeAdapter로 역직렬화 라운드트립."""
    original = ErrorEvent(
        thread_id="t",
        seq=5,
        node="core_solver",
        step_idx=2,
        payload=ErrorPayload(
            code="tool_error",
            message="boom",
            tool_call_id="call-1",
        ),
    )
    out = to_sse(original)
    adapter: TypeAdapter = TypeAdapter(SSEEvent)
    restored = adapter.validate_json(out["data"])

    assert isinstance(restored, ErrorEvent)
    assert restored.payload.code == "tool_error"
    assert restored.payload.tool_call_id == "call-1"
    assert restored.node == "core_solver"
    assert restored.step_idx == 2


def test_to_sse_credit_settled_serializes_log() -> None:
    event = CreditSettledEvent(
        thread_id="t",
        seq=1,
        payload=CreditSettledPayload(
            reserved=10.0,
            actual=8.0,
            refunded=2.0,
            log=[CreditEntry(node="core_solver", action="llm", cost=8.0)],
        ),
    )
    out = to_sse(event)
    parsed = json.loads(out["data"])
    assert parsed["payload"]["refunded"] == 2.0
    assert parsed["payload"]["log"][0]["node"] == "core_solver"


def test_to_sse_node_result() -> None:
    event = NodeResultEvent(
        thread_id="t",
        seq=3,
        node="core_solver",
        step_idx=0,
        payload=NodeResultPayload(status="done", duration_ms=1234),
    )
    out = to_sse(event)
    parsed = json.loads(out["data"])
    assert parsed["payload"] == {
        "status": "done",
        "duration_ms": 1234,
        "error_code": None,
    }


def test_to_sse_page_start() -> None:
    event = PageStartEvent(
        thread_id="t",
        seq=0,
        payload=PageStartPayload(
            plan=[
                PlanStep(action="solve", description="step1"),
                PlanStep(action="video", description="step2"),
            ],
            selected_model="sonnet",
            difficulty="medium",
            route="math_task",
            use_page=True,
        ),
    )
    out = to_sse(event)
    parsed = json.loads(out["data"])
    assert parsed["payload"]["selected_model"] == "sonnet"
    assert len(parsed["payload"]["plan"]) == 2


# ────────────────────────────────────────────────────────────────────────────
# EventType ↔ Envelope 매핑 누락 가드
# ────────────────────────────────────────────────────────────────────────────


def test_every_event_type_has_envelope_class() -> None:
    """SSEEvent union이 EventType Literal의 모든 값을 커버하는지 검증.

    새 EventType 추가 시 envelope 클래스 등록 누락을 컴파일/CI에서 잡는다.
    """
    declared = set(get_args(EventType))

    # SSEEvent는 Annotated[Union, Field(...)] 형태. get_args의 첫 인자가 Union
    annotated_args = get_args(SSEEvent)
    union = annotated_args[0]
    envelope_classes = get_args(union)

    mapped_types = set()
    for cls in envelope_classes:
        type_field = cls.model_fields["type"]
        # Literal 단일 값 추출
        mapped_types.add(get_args(type_field.annotation)[0])

    assert mapped_types == declared, (
        f"EventType ↔ envelope 매핑 불일치 — 누락: {declared - mapped_types}, "
        f"잉여: {mapped_types - declared}"
    )


# ────────────────────────────────────────────────────────────────────────────
# to_stream_v2 — 백엔드(Proovy-server) /stream/v2 vocab 변환
# ────────────────────────────────────────────────────────────────────────────


def test_to_stream_v2_token_maps_to_llm_token_delta() -> None:
    """token → event:llm.token.delta, data:{delta, thread_id}."""
    frame = to_stream_v2(TokenEvent(thread_id="th-1", seq=3, payload=TokenPayload(delta="안녕")))
    assert frame is not None
    assert frame["event"] == "llm.token.delta"
    # id는 싣지 않는다 — 내부 이벤트 drop으로 seq가 불연속이라 gap 오탐 방지
    assert "id" not in frame
    data = json.loads(frame["data"])
    assert data == {"delta": "안녕", "thread_id": "th-1"}


def test_to_stream_v2_done_maps_to_run_completed() -> None:
    """done → event:run.completed, data:{thread_id}."""
    frame = to_stream_v2(DoneEvent(thread_id="th-1", seq=9, payload=DonePayload()))
    assert frame is not None
    assert frame["event"] == "run.completed"
    data = json.loads(frame["data"])
    assert data == {"thread_id": "th-1"}


def test_to_stream_v2_error_maps_to_run_failed_with_message() -> None:
    """error → event:run.failed, data:{message, thread_id}."""
    frame = to_stream_v2(
        ErrorEvent(thread_id="th-1", seq=5, payload=ErrorPayload(message="실패함"))
    )
    assert frame is not None
    assert frame["event"] == "run.failed"
    data = json.loads(frame["data"])
    assert data == {"message": "실패함", "thread_id": "th-1"}


def test_to_stream_v2_drops_internal_only_events() -> None:
    """백엔드가 소비하지 않는 내부 이벤트(node_result 등)는 None으로 drop."""
    dropped = to_stream_v2(
        NodeResultEvent(
            thread_id="th-1",
            seq=2,
            payload=NodeResultPayload(status="done", duration_ms=10),
        )
    )
    assert dropped is None
