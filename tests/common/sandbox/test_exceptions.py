"""Sandbox exception tests."""

from proovy_agent.common.sandbox.exceptions import (
    CodeExecutionError,
    SandboxCreationError,
    SandboxError,
    SandboxTimeoutError,
    SandboxUnavailableError,
)


def test_sandbox_exception_hierarchy() -> None:
    """Sandbox exceptions inherit from the expected base classes."""
    assert issubclass(SandboxCreationError, SandboxError)
    assert issubclass(SandboxUnavailableError, SandboxError)
    assert issubclass(SandboxTimeoutError, CodeExecutionError)
    assert issubclass(SandboxTimeoutError, SandboxError)
