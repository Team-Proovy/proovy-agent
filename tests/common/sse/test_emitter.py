"""SSEEmitter 단위 테스트."""

import json

from pydantic import BaseModel
import pytest

from proovy_agent.common.sse import emitter as emitter_module
from proovy_agent.common.sse.context import EmitContext, current_emit_context
from proovy_agent.common.sse.emitter import SSEEmitter
from proovy_agent.common.sse.events import TokenPayload, ToolStartPayload


async def _collect(emitter: SSEEmitter) -> list[dict]:
    """close() 후 stream()에서 모든 이벤트를 수집한다."""
    await emitter.close()
    return [event async for event in emitter.stream()]


async def test_emit_and_stream() -> None:
    """emit()한 이벤트가 close() 후에도 보존되어 stream()에서 순서대로 반환된다."""
    emitter = SSEEmitter(thread_id="t")

    await emitter.emit(TokenPayload(delta="안녕"))
    await emitter.emit(ToolStartPayload(name="code_generate", label="생성 중"))

    events = await _collect(emitter)

    assert len(events) == 2
    assert events[0]["event"] == "token"
    assert events[1]["event"] == "tool_start"
    # envelope 메타 + id 형식
    assert events[0]["id"] == "t:0"
    assert events[1]["id"] == "t:1"
    assert json.loads(events[0]["data"])["payload"]["delta"] == "안녕"


async def test_close_idempotent() -> None:
    """close()를 여러 번 호출해도 sentinel이 중복 삽입되지 않는다."""
    emitter = SSEEmitter(thread_id="t")
    await emitter.emit(TokenPayload(delta="hello"))

    await emitter.close()
    await emitter.close()
    await emitter.close()

    events = [event async for event in emitter.stream()]
    assert len(events) == 1


async def test_emit_after_close_ignored() -> None:
    """close() 이후 emit()은 조용히 무시되고 seq도 증가하지 않는다."""
    emitter = SSEEmitter(thread_id="t")
    await emitter.emit(TokenPayload(delta="before"))
    await emitter.close()

    await emitter.emit(TokenPayload(delta="after"))

    events = [event async for event in emitter.stream()]
    assert len(events) == 1
    assert "before" in events[0]["data"]


async def test_emit_injects_emit_context() -> None:
    """current_emit_context의 node/step_idx가 envelope에 자동 주입된다."""
    emitter = SSEEmitter(thread_id="t")
    token = current_emit_context.set(EmitContext(node="core_solver", step_idx=2))
    try:
        await emitter.emit(TokenPayload(delta="x"))
    finally:
        current_emit_context.reset(token)

    events = await _collect(emitter)
    data = json.loads(events[0]["data"])
    assert data["node"] == "core_solver"
    assert data["step_idx"] == 2


async def test_emit_without_context_uses_defaults() -> None:
    """EmitContext 미설정 시 node='', step_idx=0 기본값을 쓴다."""
    emitter = SSEEmitter(thread_id="t")
    await emitter.emit(TokenPayload(delta="x"))

    events = await _collect(emitter)
    data = json.loads(events[0]["data"])
    assert data["node"] == ""
    assert data["step_idx"] == 0


async def test_emit_queue_full_drops_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """큐 포화 시 raise하지 않고 드롭하되 seq는 소비된다 (gap 신호)."""
    monkeypatch.setattr(emitter_module, "_QUEUE_MAX_SIZE", 2)
    emitter = SSEEmitter(thread_id="t")

    for _ in range(10):
        await emitter.emit(TokenPayload(delta="x"))  # 일부 드롭, raise 없음

    assert emitter._seq == 10  # seq는 전부 소비됨


async def test_emit_unregistered_payload_drops_without_raising() -> None:
    """매핑에 없는 payload는 ERROR 로그 후 드롭, raise하지 않고 seq는 소비된다."""

    class UnknownPayload(BaseModel):
        foo: str = "bar"

    emitter = SSEEmitter(thread_id="t")
    await emitter.emit(UnknownPayload())

    assert emitter._seq == 1
    events = await _collect(emitter)
    assert events == []  # 드롭되어 스트림에 없음
