"""Sandbox Pydantic models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from proovy_agent.common.sandbox.preamble import get_whitelisted_preamble


class SandboxConfig(BaseModel):
    """Sandbox creation settings."""

    snapshot: str
    cpu: int = 2
    memory: int = 2
    disk: int = 5
    auto_stop_interval: int = 5
    code_timeout: int = 60
    max_output_chars: int = 10_000
    network_block_all: bool = True
    preamble_code: str = ""

    @classmethod
    def from_settings(cls, settings: Any) -> SandboxConfig:
        """Create sandbox config from application settings."""
        return cls(
            snapshot=settings.daytona_snapshot,
            cpu=settings.daytona_sandbox_cpu,
            memory=settings.daytona_sandbox_memory,
            disk=settings.daytona_sandbox_disk,
            auto_stop_interval=settings.daytona_auto_stop_interval,
            code_timeout=settings.daytona_code_timeout,
            max_output_chars=settings.daytona_max_output_chars,
            preamble_code=get_whitelisted_preamble(settings.sandbox_preamble_name),
        )


class RecoveryHint(StrEnum):
    """Executor recovery hint for failed code execution."""

    NONE = "none"
    RESET_RECOMMENDED = "reset_recommended"
    UNRECOVERABLE = "unrecoverable"


class CodeError(BaseModel):
    """Structured Python execution error."""

    name: str
    value: str
    traceback: str


class CodeExecutionResult(BaseModel):
    """Python code execution result."""

    stdout: str
    stderr: str = ""
    error: CodeError | None = None
    success: bool
    truncated: bool = False
    recovery_hint: RecoveryHint = RecoveryHint.NONE


class ShellResult(BaseModel):
    """Shell command execution result."""

    stdout: str
    exit_code: int
    success: bool


class ExecutorStatus(StrEnum):
    """In-memory executor status for request context."""

    NONE = "none"
    CREATING = "creating"
    READY = "ready"
    FAILED = "failed"
    CLEANED = "cleaned"
