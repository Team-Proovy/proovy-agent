"""CoreSolver 에이전트 단위 테스트."""

from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from proovy_agent.common.sandbox.executor_var import current_executor
from proovy_agent.graph.agents.core_solver.agent import (
    _code_execute_succeeded,
    _extract_generated_messages,
    _message_text,
    _phase1_verify,
    _trim_tool_messages,
    core_solver,
)
from proovy_agent.graph.state import ProovyState
from proovy_agent.graph.tools.code_execute import code_execute


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, *, tool_choice: object = None, **kwargs: object) -> object:
        return self


class _FakeExecutor:
    def __init__(
        self,
        *,
        stdout: str = "2\n",
        stderr: str = "",
        success: bool = True,
        error: object | None = None,
        results: list[dict[str, object]] | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.success = success
        self.error = error
        self.results = results or []
        self.codes: list[str] = []

    async def run_python(self, code: str) -> object:
        index = len(self.codes)
        self.codes.append(code)
        if self.results:
            result = self.results[min(index, len(self.results) - 1)]
            return SimpleNamespace(
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                success=result.get("success", True),
                error=result.get("error"),
            )
        return SimpleNamespace(
            stdout=self.stdout,
            stderr=self.stderr,
            success=self.success,
            error=self.error,
        )


class _FakeSandboxManager:
    def __init__(self, executor: _FakeExecutor) -> None:
        self.executor = executor
        self.destroyed = False

    async def create_executor(self, thread_id: str) -> _FakeExecutor:
        return self.executor

    async def destroy_executor(self, executor: _FakeExecutor) -> None:
        self.destroyed = True


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


def test_extract_generated_messages_ignores_normalized_input_prefix() -> None:
    """입력 메시지 id가 정규화되어도 새 AI/Tool 메시지만 추출한다."""
    input_messages = [
        HumanMessage(content="1+1은?"),
        AIMessage(content="이전 답변", metadata={"display": "content"}),
    ]
    output_messages = [
        HumanMessage(content="1+1은?", id="normalized-human"),
        AIMessage(content="이전 답변", id="normalized-ai"),
        AIMessage(content="새 검증 메시지"),
    ]

    generated = _extract_generated_messages(input_messages, output_messages)

    assert len(generated) == 1
    assert isinstance(generated[0], AIMessage)
    assert generated[0].content == "새 검증 메시지"


def test_message_text_normalizes_multimodal_blocks() -> None:
    """멀티모달 content block도 downstream 소비 가능한 문자열로 정규화한다."""
    message = AIMessage(content=[{"type": "text", "text": "검증된 "}, {"text": "풀이"}, "3"])

    assert _message_text(message) == "검증된 풀이3"


# ── _phase1_verify ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase1_no_tool_calls_returns_not_verified() -> None:
    """도구 호출 없이 LLM이 바로 응답하면 verified=False."""
    fake_llm = _ToolCallingFakeModel(responses=[AIMessage(content="그냥 답변", tool_calls=[])])

    with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm):
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
    fake_llm = _ToolCallingFakeModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call]),
            AIMessage(content="1단계로 계산하면 1+1=2이므로 답은 2입니다.", tool_calls=[]),
        ]
    )
    token = current_executor.set(_FakeExecutor())

    try:
        with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm):
            summary, messages, execute_count, verified, _, _ = await _phase1_verify(
                _state(), emitter=None
            )
    finally:
        current_executor.reset(token)

    assert verified
    assert execute_count == 1
    assert "답은 2" in summary
    assert any(
        isinstance(msg, ToolMessage) and "stdout:\n2" in str(msg.content) for msg in messages
    )
    assert any(
        isinstance(msg, AIMessage)
        and getattr(msg, "metadata", {}).get("kind") == "verified_solution"
        for msg in messages
    )


@pytest.mark.asyncio
async def test_phase1_normalizes_verified_solution_content() -> None:
    """verified_solution 태그가 붙은 메시지는 문자열 content로 보존한다."""
    tool_call = {"name": "code_execute", "args": {"code": "print(2)"}, "id": "tc1"}
    fake_llm = _ToolCallingFakeModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call]),
            AIMessage(
                content=[{"type": "text", "text": "검증된 "}, {"text": "풀이"}],
                tool_calls=[],
            ),
        ]
    )
    token = current_executor.set(_FakeExecutor())

    try:
        with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm):
            _, messages, _, verified, _, _ = await _phase1_verify(_state(), emitter=None)
    finally:
        current_executor.reset(token)

    assert verified
    verified_message = next(
        msg
        for msg in messages
        if isinstance(msg, AIMessage)
        and getattr(msg, "metadata", {}).get("kind") == "verified_solution"
    )
    assert verified_message.content == "검증된 풀이"


@pytest.mark.asyncio
async def test_phase1_failed_code_execute_does_not_set_verified() -> None:
    """code_execute가 실패(exit_code: 1)하면 verified=False."""
    tool_call = {"name": "code_execute", "args": {"code": "raise ValueError()"}, "id": "tc1"}
    fake_llm = _ToolCallingFakeModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call]),
            AIMessage(content="실패", tool_calls=[]),
        ]
    )
    token = current_executor.set(_FakeExecutor(stderr="ValueError\n", success=False))

    try:
        with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm):
            _, messages, execute_count, verified, _, _ = await _phase1_verify(
                _state(), emitter=None
            )
    finally:
        current_executor.reset(token)

    assert not verified
    assert execute_count == 1
    assert not any(
        isinstance(msg, AIMessage)
        and getattr(msg, "metadata", {}).get("kind") == "verified_solution"
        for msg in messages
    )


@pytest.mark.asyncio
async def test_phase1_uses_last_code_execute_result_for_verification() -> None:
    """이전 실행이 성공해도 마지막 code_execute가 실패하면 verified=False."""
    success_call = {"name": "code_execute", "args": {"code": "print(2)"}, "id": "tc-success"}
    failure_call = {
        "name": "code_execute",
        "args": {"code": "raise ValueError()"},
        "id": "tc-failure",
    }
    fake_llm = _ToolCallingFakeModel(
        responses=[
            AIMessage(content="", tool_calls=[success_call]),
            AIMessage(content="", tool_calls=[failure_call]),
            AIMessage(content="마지막 실행 결과를 정리했습니다.", tool_calls=[]),
        ]
    )
    executor = _FakeExecutor(
        results=[
            {"stdout": "2\n", "success": True},
            {"stderr": "ValueError\n", "success": False},
        ]
    )
    token = current_executor.set(executor)

    try:
        with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm):
            _, messages, execute_count, verified, _, _ = await _phase1_verify(
                _state(), emitter=None
            )
    finally:
        current_executor.reset(token)

    assert not verified
    assert execute_count == 2
    assert not any(
        isinstance(msg, AIMessage)
        and getattr(msg, "metadata", {}).get("kind") == "verified_solution"
        for msg in messages
    )


@pytest.mark.asyncio
async def test_phase1_max_iteration_returns_current_result() -> None:
    """모델이 계속 도구만 호출해도 max iteration에서 현재 결과로 종료한다."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "code_execute", "args": {"code": f"print({idx})"}, "id": f"tc{idx}"}
            ],
        )
        for idx in range(5)
    ]
    responses.append(AIMessage(content="1단계: 코드 실행 결과 1+1=2이므로 답은 2입니다."))
    fake_llm = _ToolCallingFakeModel(responses=responses)
    token = current_executor.set(_FakeExecutor(stdout="2\n"))

    try:
        with patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm):
            summary, messages, execute_count, verified, llm_calls, _ = await _phase1_verify(
                _state(), emitter=None
            )
    finally:
        current_executor.reset(token)

    assert verified
    assert execute_count == 5
    assert llm_calls == 6
    assert "답은 2" in summary
    assert "stdout:" not in summary
    assert any(
        isinstance(msg, AIMessage)
        and getattr(msg, "metadata", {}).get("kind") == "verified_solution"
        for msg in messages
    )


@pytest.mark.asyncio
async def test_core_solver_preserves_evidence_and_verified_solution() -> None:
    """한 solve 후 code args, stdout, verified_solution 세 evidence가 모두 남는다."""
    tool_call = {"name": "code_execute", "args": {"code": "print(2)"}, "id": "tc1"}
    fake_llm = _ToolCallingFakeModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call]),
            AIMessage(content="1단계: 1+1=2입니다. 따라서 답은 2입니다.", tool_calls=[]),
        ]
    )
    executor = _FakeExecutor(stdout="2\n")
    manager = _FakeSandboxManager(executor)

    with (
        patch("proovy_agent.graph.agents.core_solver.agent.get_llm", return_value=fake_llm),
        patch("proovy_agent.graph.agents.core_solver.agent.get_daytona_client"),
        patch("proovy_agent.graph.agents.core_solver.agent.SandboxManager", return_value=manager),
    ):
        result = await core_solver(_state(explanation_mode="brief"))

    messages = result["messages"]
    assert any(
        isinstance(msg, AIMessage)
        and any(
            call["name"] == "code_execute" and call["args"]["code"] == "print(2)"
            for call in msg.tool_calls
        )
        for msg in messages
    )
    assert any(
        isinstance(msg, ToolMessage) and "stdout:\n2" in str(msg.content) for msg in messages
    )
    verified_messages = [
        msg
        for msg in messages
        if isinstance(msg, AIMessage)
        and getattr(msg, "metadata", {}).get("kind") == "verified_solution"
    ]
    assert len(verified_messages) == 1
    assert verified_messages[0].metadata["display"] == "content"
    assert manager.destroyed
    assert not any(entry.action == "llm_call_explain" for entry in result["credit_log"])
    assert result["current_phase"] == "verify"


@pytest.mark.asyncio
async def test_code_execute_returns_full_stdout_for_state_evidence() -> None:
    """ToolMessage evidence용 반환값은 SSE trim과 별개로 풀텍스트 stdout을 유지한다."""
    long_stdout = "x" * 700
    token = current_executor.set(_FakeExecutor(stdout=long_stdout))

    try:
        result = await code_execute.ainvoke({"code": "print('x')"})
    finally:
        current_executor.reset(token)

    assert long_stdout in result
    assert "TRIMMED" not in result
