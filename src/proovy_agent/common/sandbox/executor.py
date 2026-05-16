"""Daytona Sandbox를 감싸는 CodeExecutor."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from daytona import AsyncSandbox


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

    @property
    def sandbox(self) -> AsyncSandbox:
        return self._sandbox

    async def cleanup(self) -> None:
        pass
