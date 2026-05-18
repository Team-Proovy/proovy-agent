"""SSEEmitter 단위 테스트."""

from proovy_agent.common.sse.emitter import SSEEmitter


async def _collect(emitter: SSEEmitter) -> list[dict]:
    """close() 후 stream()에서 모든 이벤트를 수집한다."""
    await emitter.close()
    return [event async for event in emitter.stream()]


async def test_emit_and_stream() -> None:
    """emit()한 이벤트가 stream()에서 순서대로 반환된다."""
    emitter = SSEEmitter()

    await emitter.emit("token", {"text": "안녕"})
    await emitter.emit("tool_start", {"name": "code_generate"})

    events = await _collect(emitter)

    assert len(events) == 2
    assert events[0]["event"] == "token"
    assert events[1]["event"] == "tool_start"


async def test_close_idempotent() -> None:
    """close()를 여러 번 호출해도 sentinel이 중복 삽입되지 않는다."""
    emitter = SSEEmitter()
    await emitter.emit("token", {"text": "hello"})

    await emitter.close()
    await emitter.close()
    await emitter.close()

    events = [event async for event in emitter.stream()]
    assert len(events) == 1


async def test_emit_after_close_ignored() -> None:
    """close() 이후 emit()은 조용히 무시되어 이벤트가 추가되지 않는다."""
    emitter = SSEEmitter()
    await emitter.emit("token", {"text": "before"})
    await emitter.close()

    await emitter.emit("token", {"text": "after"})

    events = [event async for event in emitter.stream()]
    assert len(events) == 1
    assert "before" in events[0]["data"]
