"""CreditSettler 노드 단위 테스트."""

import pytest

from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.emitter import SSEEmitter
from proovy_agent.graph.nodes.credit_settler import credit_settler
from proovy_agent.graph.state import CreditEntry, ProovyState


def _state(entries: list[CreditEntry]) -> ProovyState:
    return ProovyState(user_id="u", thread_id="t", credit_log=entries)


@pytest.mark.asyncio
async def test_sums_total_credit() -> None:
    state = _state(
        [
            CreditEntry(node="core_solver", action="llm_call_verify", model="flash", cost=2.0),
            CreditEntry(node="core_solver", action="code_execute", cost=1.0),
        ]
    )
    result = await credit_settler(state)
    assert result["total_credit_cost"] == 3.0


@pytest.mark.asyncio
async def test_emits_credit_settled_event() -> None:
    emitter = SSEEmitter(thread_id="t")
    token = current_emitter.set(emitter)
    try:
        await credit_settler(_state([CreditEntry(node="x", action="a", cost=5.0)]))
    finally:
        current_emitter.reset(token)

    await emitter.close()
    events = [e async for e in emitter.stream()]
    assert any(e["event"] == "credit_settled" for e in events)


@pytest.mark.asyncio
async def test_no_emitter_does_not_raise() -> None:
    state = _state([CreditEntry(node="x", action="a", cost=1.0)])
    result = await credit_settler(state)
    assert result["total_credit_cost"] == 1.0


@pytest.mark.asyncio
async def test_empty_log_total_is_zero() -> None:
    result = await credit_settler(_state([]))
    assert result["total_credit_cost"] == 0.0
