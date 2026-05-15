"""Sandbox Pydantic models."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, model_validator

from proovy_agent.common.sandbox.preamble import get_whitelisted_preamble


class _DaytonaSettingsProtocol(Protocol):
    """Settings fields required to build SandboxConfig."""

    daytona_snapshot: str
    daytona_sandbox_cpu: int
    daytona_sandbox_memory: int
    daytona_sandbox_disk: int
    daytona_auto_stop_interval: int
    daytona_code_timeout: int
    daytona_max_output_chars: int
    sandbox_preamble_name: str


class SandboxConfig(BaseModel):
    """Sandbox creation settings."""

    snapshot: str
    cpu: int = 2  # CPU cores
    memory: int = 2  # GiB
    disk: int = 5  # GiB
    auto_stop_interval: int = 5  # minutes
    code_timeout: int = 60  # seconds
    max_output_chars: int = 10_000  # characters
    network_block_all: bool = True
    preamble_code: str = ""

    @classmethod
    def from_settings(cls, settings: _DaytonaSettingsProtocol) -> SandboxConfig:
        """Create config from settings and force network isolation.

        network_block_all is intentionally not settings-driven: MVP sandboxes
        run with preinstalled packages and blocked network access for safety.
        """
        return cls(
            snapshot=settings.daytona_snapshot,
            cpu=settings.daytona_sandbox_cpu,
            memory=settings.daytona_sandbox_memory,
            disk=settings.daytona_sandbox_disk,
            auto_stop_interval=settings.daytona_auto_stop_interval,
            code_timeout=settings.daytona_code_timeout,
            max_output_chars=settings.daytona_max_output_chars,
            network_block_all=True,
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

    @model_validator(mode="after")
    def validate_error_consistency(self) -> CodeExecutionResult:
        """Ensure successful executions do not carry errors."""
        if self.success and self.error is not None:
            raise ValueError("error must be None when success is True")
        return self


class ShellResult(BaseModel):
    """Shell command execution result."""

    stdout: str
    exit_code: int
    success: bool

    @model_validator(mode="after")
    def validate_success_matches_exit_code(self) -> ShellResult:
        """Ensure success reflects the shell exit code."""
        if self.success != (self.exit_code == 0):
            raise ValueError("success must match exit_code")
        return self


class ExecutorStatus(StrEnum):
    """In-memory executor status for request context."""

    NONE = "none"
    CREATING = "creating"
    READY = "ready"
    FAILED = "failed"
    CLEANED = "cleaned"
