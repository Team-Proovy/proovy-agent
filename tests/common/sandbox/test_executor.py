"""CodeExecutor tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from proovy_agent.common.sandbox import executor as executor_module
from proovy_agent.common.sandbox.exceptions import CodeExecutionError, SandboxTimeoutError
from proovy_agent.common.sandbox.models import RecoveryHint


@dataclass
class FakeOutputMessage:
    output: str


@dataclass
class FakeRuntimeError:
    name: str
    value: str
    traceback: str


@dataclass
class FakeRuntimeResult:
    stdout: str = ""
    stderr: str = ""
    error: FakeRuntimeError | None = None


@dataclass
class FakeRunCall:
    result: FakeRuntimeResult | None = None
    exception: Exception | None = None
    stdout_chunks: list[str] = field(default_factory=list)
    stderr_chunks: list[str] = field(default_factory=list)


class FakeCodeInterpreter:
    def __init__(self, calls: list[FakeRunCall] | None = None) -> None:
        self.calls = list(calls or [])
        self.create_context_calls: list[object | None] = []
        self.run_code_calls: list[dict[str, object]] = []
        self.delete_context_calls: list[object] = []
        self.context_counter = 0

    async def create_context(self, cwd: object | None = None) -> str:
        self.create_context_calls.append(cwd)
        self.context_counter += 1
        return f"ctx-{self.context_counter}"

    async def run_code(
        self,
        code: str,
        *,
        context: object | None = None,
        on_stdout=None,
        on_stderr=None,
        on_error=None,
        envs: dict[str, str] | None = None,
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> FakeRuntimeResult:
        self.run_code_calls.append(
            {
                "code": code,
                "context": context,
                "on_stdout": on_stdout,
                "on_stderr": on_stderr,
                "on_error": on_error,
                "envs": envs,
                "timeout": timeout,
            }
        )
        call = self.calls.pop(0)
        for chunk in call.stdout_chunks:
            if on_stdout is not None:
                on_stdout(FakeOutputMessage(chunk))
        for chunk in call.stderr_chunks:
            if on_stderr is not None:
                on_stderr(FakeOutputMessage(chunk))
        if call.exception is not None:
            raise call.exception
        assert call.result is not None
        return call.result

    async def delete_context(self, context: object) -> None:
        self.delete_context_calls.append(context)


class FakeSandbox:
    def __init__(self, calls: list[FakeRunCall] | None = None) -> None:
        self.code_interpreter = FakeCodeInterpreter(calls)


class DeleteFailingInterpreter(FakeCodeInterpreter):
    async def delete_context(self, context: object) -> None:
        self.delete_context_calls.append(context)
        raise RuntimeError("delete failed")


class DeleteFailingSandbox(FakeSandbox):
    def __init__(self, calls: list[FakeRunCall] | None = None) -> None:
        self.code_interpreter = DeleteFailingInterpreter(calls)


class DaytonaSdkError(Exception):
    pass


class DaytonaTimeoutError(Exception):
    pass


@pytest.fixture(autouse=True)
def fake_sdk_exception_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor_module, "_SDK_ERROR_TYPES", (DaytonaSdkError,), raising=False)
    monkeypatch.setattr(
        executor_module, "_TIMEOUT_ERROR_TYPES", (DaytonaTimeoutError,), raising=False
    )


async def test_classify_error_none_returns_none() -> None:
    assert executor_module._classify_error(None) is RecoveryHint.NONE


@pytest.mark.parametrize(
    ("error_name", "expected"),
    [
        ("NameError", RecoveryHint.RESET_RECOMMENDED),
        ("ImportError", RecoveryHint.RESET_RECOMMENDED),
        ("ModuleNotFoundError", RecoveryHint.RESET_RECOMMENDED),
        ("UnboundLocalError", RecoveryHint.RESET_RECOMMENDED),
        ("ZeroDivisionError", RecoveryHint.NONE),
    ],
)
async def test_classify_error_uses_reset_hint_only_for_selected_names(
    error_name: str, expected: RecoveryHint
) -> None:
    error = FakeRuntimeError(error_name, "boom", "trace")

    assert executor_module._classify_error(error) is expected


async def test_ensure_context_creates_context_runs_preamble_once_and_reuses_it() -> None:
    sandbox = FakeSandbox([FakeRunCall(result=FakeRuntimeResult())])
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    first = await code_executor._ensure_context()
    second = await code_executor._ensure_context()

    assert first == "ctx-1"
    assert second == "ctx-1"
    assert sandbox.code_interpreter.create_context_calls == [None]
    assert len(sandbox.code_interpreter.run_code_calls) == 1
    assert sandbox.code_interpreter.run_code_calls[0]["code"] == "import math\n"
    assert sandbox.code_interpreter.run_code_calls[0]["context"] == "ctx-1"
    assert sandbox.code_interpreter.run_code_calls[0]["timeout"] == 30


async def test_ensure_context_deletes_context_and_clears_state_when_preamble_fails() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(
                result=FakeRuntimeResult(error=FakeRuntimeError("ImportError", "nope", "traceback"))
            )
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import badlib\n")

    with pytest.raises(CodeExecutionError, match="Preamble 실행 실패"):
        await code_executor._ensure_context()

    assert sandbox.code_interpreter.delete_context_calls == ["ctx-1"]
    assert code_executor._context is None


async def test_run_python_collects_streams_from_synchronous_callbacks() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(
                result=FakeRuntimeResult(),
                stdout_chunks=["hello", " world"],
                stderr_chunks=["warn"],
            ),
        ]
    )
    code_executor = executor_module.CodeExecutor(
        sandbox=sandbox,
        code_timeout=17,
        preamble_code="import math\n",
    )

    result = await code_executor.run_python("print('ok')")

    on_stdout = sandbox.code_interpreter.run_code_calls[-1]["on_stdout"]
    on_stderr = sandbox.code_interpreter.run_code_calls[-1]["on_stderr"]

    assert callable(on_stdout)
    assert callable(on_stderr)
    assert result.success is True
    assert result.stdout == "hello world"
    assert result.stderr == "warn"
    assert result.error is None
    assert result.recovery_hint is RecoveryHint.NONE
    assert result.truncated is False
    assert sandbox.code_interpreter.run_code_calls[-1]["code"] == "print('ok')"
    assert sandbox.code_interpreter.run_code_calls[-1]["context"] == "ctx-1"
    assert sandbox.code_interpreter.run_code_calls[-1]["timeout"] == 17


async def test_run_python_truncates_total_output_and_marks_stream_that_exceeded_limit() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(
                result=FakeRuntimeResult(),
                stdout_chunks=["abcd", "ef"],
                stderr_chunks=["XYZ"],
            ),
        ]
    )
    code_executor = executor_module.CodeExecutor(
        sandbox=sandbox,
        max_output_chars=5,
        preamble_code="import math\n",
    )

    result = await code_executor.run_python("print('too much')")

    assert result.success is True
    assert result.truncated is True
    assert result.stdout == "abcde... [output truncated to 5 chars]"
    assert result.stderr == ""


async def test_run_python_converts_runtime_result_error_to_code_error_and_hint() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(
                result=FakeRuntimeResult(
                    error=FakeRuntimeError("NameError", "x is not defined", "tb")
                )
            ),
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    result = await code_executor.run_python("x")

    assert result.success is False
    assert result.error is not None
    assert result.error.name == "NameError"
    assert result.error.value == "x is not defined"
    assert result.error.traceback == "tb"
    assert result.recovery_hint is RecoveryHint.RESET_RECOMMENDED


async def test_run_python_translates_daytona_timeout_exception() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(exception=DaytonaTimeoutError("timed out")),
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    with pytest.raises(SandboxTimeoutError, match="timed out"):
        await code_executor.run_python("while True: pass")


async def test_run_python_translates_daytona_sdk_errors() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(exception=DaytonaSdkError("sdk exploded")),
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    with pytest.raises(CodeExecutionError, match="sdk exploded") as exc_info:
        await code_executor.run_python("print('hi')")

    assert isinstance(exc_info.value.__cause__, DaytonaSdkError)


async def test_run_python_does_not_treat_generic_sdk_errors_as_timeouts() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(exception=DaytonaSdkError("generic sdk failure")),
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    with pytest.raises(CodeExecutionError, match="generic sdk failure"):
        await code_executor.run_python("print('hi')")


async def test_run_python_propagates_programmer_errors_unchanged() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(exception=AssertionError("bug in caller")),
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    with pytest.raises(AssertionError, match="bug in caller"):
        await code_executor.run_python("assert False")


async def test_reset_context_deletes_old_context_recreates_and_reruns_preamble() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(result=FakeRuntimeResult()),
            FakeRunCall(result=FakeRuntimeResult()),
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    original = await code_executor._ensure_context()
    await code_executor.reset_context()

    assert original == "ctx-1"
    assert code_executor._context == "ctx-2"
    assert sandbox.code_interpreter.delete_context_calls == ["ctx-1"]
    assert sandbox.code_interpreter.create_context_calls == [None, None]
    assert [call["context"] for call in sandbox.code_interpreter.run_code_calls] == [
        "ctx-1",
        "ctx-2",
    ]


async def test_reset_context_without_existing_context_still_creates_one() -> None:
    sandbox = FakeSandbox([FakeRunCall(result=FakeRuntimeResult())])
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import math\n")

    await code_executor.reset_context()

    assert code_executor._context == "ctx-1"
    assert sandbox.code_interpreter.delete_context_calls == []
    assert sandbox.code_interpreter.create_context_calls == [None]


async def test_reset_context_clears_new_context_if_preamble_fails() -> None:
    sandbox = FakeSandbox(
        [
            FakeRunCall(
                result=FakeRuntimeResult(
                    error=FakeRuntimeError("ImportError", "bad preamble", "tb")
                )
            )
        ]
    )
    code_executor = executor_module.CodeExecutor(sandbox=sandbox, preamble_code="import broken\n")

    with pytest.raises(CodeExecutionError, match="Preamble 실행 실패"):
        await code_executor.reset_context()

    assert sandbox.code_interpreter.delete_context_calls == ["ctx-1"]
    assert code_executor._context is None


async def test_cleanup_deletes_current_context_and_swallows_delete_failure() -> None:
    ok_sandbox = FakeSandbox([FakeRunCall(result=FakeRuntimeResult())])
    code_executor = executor_module.CodeExecutor(ok_sandbox, preamble_code="import math\n")
    await code_executor._ensure_context()

    await code_executor.cleanup()

    assert ok_sandbox.code_interpreter.delete_context_calls == ["ctx-1"]
    assert code_executor._context is None

    failing_sandbox = DeleteFailingSandbox([FakeRunCall(result=FakeRuntimeResult())])
    failing_executor = executor_module.CodeExecutor(failing_sandbox, preamble_code="import math\n")
    await failing_executor._ensure_context()

    await failing_executor.cleanup()

    assert failing_sandbox.code_interpreter.delete_context_calls == ["ctx-1"]
    assert failing_executor._context is None

    empty_executor = executor_module.CodeExecutor(FakeSandbox())
    await empty_executor.cleanup()
    assert empty_executor._context is None


async def test_sandbox_property_returns_underlying_sandbox() -> None:
    sandbox = FakeSandbox()
    code_executor = executor_module.CodeExecutor(sandbox)

    assert code_executor.sandbox is sandbox


async def test_run_shell_raises_not_implemented() -> None:
    code_executor = executor_module.CodeExecutor(FakeSandbox())

    with pytest.raises(NotImplementedError, match="run_shell is not implemented in the MVP"):
        await code_executor.run_shell("ls")
