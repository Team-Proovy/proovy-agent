"""Daytona Sandbox를 감싸는 CodeExecutor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from proovy_agent.common.sandbox.exceptions import CodeExecutionError, SandboxTimeoutError
from proovy_agent.common.sandbox.models import (
    CodeError,
    CodeExecutionResult,
    RecoveryHint,
    ShellResult,
)

if TYPE_CHECKING:
    from daytona import AsyncSandbox


def _load_sdk_error_types() -> tuple[type[BaseException], ...]:
    try:
        from daytona.common.errors import DaytonaError
    except ImportError:
        return ()
    return (DaytonaError,)


def _load_timeout_error_types() -> tuple[type[BaseException], ...]:
    candidates: list[type[BaseException]] = []

    try:
        from daytona.common.errors import DaytonaTimeoutError

        candidates.append(DaytonaTimeoutError)
    except ImportError:
        pass

    try:
        from httpx import TimeoutException

        candidates.append(TimeoutException)
    except ImportError:
        pass

    return tuple(candidates)


_SDK_ERROR_TYPES = _load_sdk_error_types()
_TIMEOUT_ERROR_TYPES = _load_timeout_error_types()
logger = logging.getLogger(__name__)
_RESET_RECOMMENDED_ERROR_NAMES = {
    "NameError",
    "ImportError",
    "ModuleNotFoundError",
    "UnboundLocalError",
}
_TIMEOUT_EXCEPTION_NAMES = {"TimeoutError", "TimeoutException", "DaytonaTimeoutError"}
_SDK_EXCEPTION_NAMES = {"DaytonaError", "DaytonaSdkError", "SandboxRpcError", "ApiError"}


@dataclass
class _OutputCollector:
    max_chars: int
    stdout: str = ""
    stderr: str = ""
    total_chars: int = 0
    truncated: bool = False
    truncated_stream: str | None = None

    def append(self, stream_name: str, chunk: str) -> None:
        if not chunk or self.truncated:
            return

        remaining = self.max_chars - self.total_chars
        if remaining <= 0:
            self._mark_truncated(stream_name)
            return

        accepted = chunk[:remaining]
        if stream_name == "stdout":
            self.stdout += accepted
        else:
            self.stderr += accepted
        self.total_chars += len(accepted)

        if len(accepted) < len(chunk):
            self._mark_truncated(stream_name)

    def _mark_truncated(self, stream_name: str) -> None:
        if self.truncated:
            return

        marker = f"... [output truncated to {self.max_chars} chars]"
        if stream_name == "stdout":
            self.stdout += marker
        else:
            self.stderr += marker
        self.truncated = True
        self.truncated_stream = stream_name


def _classify_error(error: Any | None) -> RecoveryHint:
    if error is None:
        return RecoveryHint.NONE

    if getattr(error, "name", None) in _RESET_RECOMMENDED_ERROR_NAMES:
        return RecoveryHint.RESET_RECOMMENDED

    return RecoveryHint.NONE


def _is_timeout_exception(exc: BaseException) -> bool:
    return (
        isinstance(exc, _TIMEOUT_ERROR_TYPES) or exc.__class__.__name__ in _TIMEOUT_EXCEPTION_NAMES
    )


def _is_sdk_exception(exc: BaseException) -> bool:
    return isinstance(exc, _SDK_ERROR_TYPES) or exc.__class__.__name__ in _SDK_EXCEPTION_NAMES


class CodeExecutor:
    """SandboxManager가 사용하는 최소 Daytona Sandbox 래퍼."""

    def __init__(
        self,
        sandbox: AsyncSandbox,
        code_timeout: int = 60,
        max_output_chars: int = 10_000,
        preamble_code: str = "",
    ) -> None:
        self._sandbox = sandbox
        self._code_timeout = code_timeout
        self._max_output_chars = max_output_chars
        self._preamble_code = preamble_code
        self._context: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def sandbox(self) -> AsyncSandbox:
        return self._sandbox

    async def _ensure_context(self) -> Any:
        async with self._lock:
            return await self._ensure_context_unlocked()

    async def _ensure_context_unlocked(self) -> Any:
        if self._context is not None:
            return self._context

        context = await self._sandbox.code_interpreter.create_context(cwd=None)
        self._context = context

        if not self._preamble_code:
            return context

        try:
            result = await self._sandbox.code_interpreter.run_code(
                self._preamble_code,
                context=context,
                timeout=min(self._code_timeout, 30),
            )
        except Exception as exc:
            await self._discard_context_unlocked(context)
            self._translate_exception(exc)

        if getattr(result, "error", None) is not None:
            error = result.error
            await self._discard_context_unlocked(context)
            raise CodeExecutionError(
                f"Preamble 실행 실패: {getattr(error, 'name', type(error).__name__)}: {getattr(error, 'value', str(error))}"
            )

        return context

    async def run_python(
        self,
        code: str,
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> CodeExecutionResult:
        async with self._lock:
            output = _OutputCollector(max_chars=self._max_output_chars)

            def on_stdout(message: Any) -> None:
                output.append("stdout", getattr(message, "output", ""))

            def on_stderr(message: Any) -> None:
                output.append("stderr", getattr(message, "output", ""))

            try:
                context = await self._ensure_context_unlocked()
                result = await self._sandbox.code_interpreter.run_code(
                    code,
                    context=context,
                    on_stdout=on_stdout,
                    on_stderr=on_stderr,
                    timeout=timeout if timeout is not None else self._code_timeout,
                )
            except Exception as exc:
                self._translate_exception(exc)

            runtime_error = getattr(result, "error", None)
            if runtime_error is not None:
                error = CodeError(
                    name=runtime_error.name,
                    value=runtime_error.value,
                    traceback=runtime_error.traceback,
                )
                return CodeExecutionResult(
                    stdout=output.stdout or getattr(result, "stdout", ""),
                    stderr=output.stderr or getattr(result, "stderr", ""),
                    error=error,
                    success=False,
                    truncated=output.truncated,
                    recovery_hint=_classify_error(runtime_error),
                )

            return CodeExecutionResult(
                stdout=output.stdout or getattr(result, "stdout", ""),
                stderr=output.stderr or getattr(result, "stderr", ""),
                error=None,
                success=True,
                truncated=output.truncated,
                recovery_hint=RecoveryHint.NONE,
            )

    @staticmethod
    def _translate_exception(exc: Exception) -> None:
        if isinstance(exc, AssertionError):
            raise exc
        if _is_timeout_exception(exc):
            raise SandboxTimeoutError(str(exc)) from exc
        if _is_sdk_exception(exc):
            raise CodeExecutionError(str(exc)) from exc
        raise exc

    async def reset_context(self) -> None:
        async with self._lock:
            old_context = self._context
            self._context = None

            if old_context is not None:
                try:
                    await self._sandbox.code_interpreter.delete_context(old_context)
                except Exception:
                    logger.warning("Context 삭제 실패 during reset_context", exc_info=True)

            await self._ensure_context_unlocked()

    async def cleanup(self) -> None:
        async with self._lock:
            context = self._context
            self._context = None
            if context is None:
                return

            try:
                await self._sandbox.code_interpreter.delete_context(context)
            except Exception:
                logger.warning("Context 삭제 실패 during cleanup", exc_info=True)

    async def _discard_context_unlocked(self, context: Any) -> None:
        if self._context == context:
            self._context = None
        try:
            await self._sandbox.code_interpreter.delete_context(context)
        except Exception:
            logger.warning("Context 삭제 실패 during discard_context", exc_info=True)

    async def run_shell(
        self,
        command: str,
        timeout: int = 120,  # noqa: ASYNC109
    ) -> ShellResult:
        raise NotImplementedError("run_shell is not implemented in the MVP")
