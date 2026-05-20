"""CoreSolver 에이전트 단위 테스트."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from proovy_agent.graph.agents.core_solver.agent import (
    _code_execute_succeeded,
    _phase1_verify,
    _trim_tool_messages,
)
from proovy_agent.graph.state import ProovyState


def _state(**kwargs: object) -> ProovyState:
    return ProovyState(
        user_id="u",
        thread_id="t",
        messages=[HumanMessage(content="1+1은?")],
        selected_model="flash",
        **kwargs,
    )


# ── _trim_tool_messages ──────────────────────────────────────────────────────


def test_trim_truncates_long_tool_message() -> None:
    msgs = [ToolMessage(content="x" * 600, tool_call_id="1")]
    trimmed = _trim_tool_messages(msgs)
    assert len(trimmed[0].content) <= 520  # 500 + "[TRIMMED]" 여유
    assert "TRIMMED" in trimmed[0].content


def test_trim_keeps_short_tool_message() -> None:
    msgs = [ToolMessage(content="short", tool_call_id="1")]
    assert _trim_tool_messages(msgs)[0].content == "short"


def test_trim_does_not_modify_non_tool_messages() -> None:
    msgs = [AIMessage(content="x" * 600)]
    trimmed = _trim_tool_messages(msgs)
    assert trimmed[0].content == "x" * 600


# ── _code_execute_succeeded ──────────────────────────────────────────────────


def test_success_output_is_verified() -> None:
    assert _code_execute_succeeded("stdout:\n2\n") is True


def test_exit_code_1_is_not_verified() -> None:
    assert _code_execute_succeeded("stderr:\nTraceback...\nexit_code: 1") is False


def test_error_keyword_is_not_verified() -> None:
    assert _code_execute_succeeded("error: NameError: name 'x' is not defined") is False


# ── _phase1_verify ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase1_no_tool_calls_returns_not_verified() -> None:
    """도구 호출 없이 LLM이 바로 응답하면 verified=False."""
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="그냥 답변", tool_calls=[]))

    with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=mock_llm):
        _, _, execute_count, verified, llm_calls, _codegen_count = await _phase1_verify(
            _state(), emitter=None
        )

    assert not verified
    assert execute_count == 0
    assert llm_calls == 1


@pytest.mark.asyncio
async def test_phase1_successful_code_execute_sets_verified() -> None:
    """code_execute가 성공(exit_code 없음)하면 verified=True."""
    tool_call = {"name": "code_execute", "args": {"code": "print(2)"}, "id": "tc1"}
    ai_with_tool = AIMessage(content="", tool_calls=[tool_call])
    ai_final = AIMessage(content="검증 완료", tool_calls=[])

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=[ai_with_tool, ai_final])

    mock_execute = AsyncMock(return_value="stdout:\n2\n")

    with (
        patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=mock_llm),
        patch.dict(
            "proovy_agent.graph.agents.core_solver.agent._TOOLS_BY_NAME",
            {"code_execute": MagicMock(ainvoke=mock_execute)},
        ),
    ):
        _, _, execute_count, verified, _, _ = await _phase1_verify(_state(), emitter=None)

    assert verified
    assert execute_count == 1


@pytest.mark.asyncio
async def test_phase1_failed_code_execute_does_not_set_verified() -> None:
    """code_execute가 실패(exit_code: 1)하면 verified=False."""
    tool_call = {"name": "code_execute", "args": {"code": "raise ValueError()"}, "id": "tc1"}
    ai_with_tool = AIMessage(content="", tool_calls=[tool_call])
    # 최대 반복 후 종료를 위해 최종 AIMessage 반환
    ai_final = AIMessage(content="실패", tool_calls=[])

    call_count = 0

    async def side_effect(*args: object, **kwargs: object) -> AIMessage:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ai_with_tool
        return ai_final

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=side_effect)

    mock_execute = AsyncMock(return_value="stderr:\nValueError\nexit_code: 1")

    with (
        patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=mock_llm),
        patch.dict(
            "proovy_agent.graph.agents.core_solver.agent._TOOLS_BY_NAME",
            {"code_execute": MagicMock(ainvoke=mock_execute)},
        ),
    ):
        _, _, execute_count, verified, _, _ = await _phase1_verify(_state(), emitter=None)

    assert not verified
    assert execute_count == 1
