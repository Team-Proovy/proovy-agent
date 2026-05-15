"""Sandbox model tests."""

from dataclasses import dataclass

import pytest

from proovy_agent.common.sandbox.models import (
    CodeError,
    CodeExecutionResult,
    ExecutorStatus,
    RecoveryHint,
    SandboxConfig,
    ShellResult,
)
from proovy_agent.common.sandbox.preamble import get_whitelisted_preamble


@dataclass
class MockSettings:
    """Minimal settings object for SandboxConfig factory tests."""

    daytona_snapshot: str = "custom-snapshot"
    daytona_sandbox_cpu: int = 4
    daytona_sandbox_memory: int = 8
    daytona_sandbox_disk: int = 20
    daytona_auto_stop_interval: int = 10
    daytona_code_timeout: int = 120
    daytona_max_output_chars: int = 12_345
    sandbox_preamble_name: str = "math_v1"


def test_sandbox_config_from_settings_maps_daytona_values() -> None:
    """SandboxConfig.from_settings maps all Daytona settings exactly."""
    config = SandboxConfig.from_settings(MockSettings())

    assert config.snapshot == "custom-snapshot"
    assert config.cpu == 4
    assert config.memory == 8
    assert config.disk == 20
    assert config.auto_stop_interval == 10
    assert config.code_timeout == 120
    assert config.max_output_chars == 12_345
    assert config.network_block_all is True
    assert config.preamble_code == get_whitelisted_preamble("math_v1")


def test_sandbox_config_from_settings_propagates_unknown_preamble_error() -> None:
    """Unknown preamble names propagate whitelist validation errors."""
    settings = MockSettings(sandbox_preamble_name="not_allowed")

    with pytest.raises(ValueError, match=r"Unknown preamble.*not_allowed"):
        SandboxConfig.from_settings(settings)


def test_code_execution_result_dumps_recovery_hint_as_json_value() -> None:
    """CodeExecutionResult serializes enum fields predictably in JSON mode."""
    result = CodeExecutionResult(stdout="ok", success=True)

    assert result.model_dump(mode="json") == {
        "stdout": "ok",
        "stderr": "",
        "error": None,
        "success": True,
        "truncated": False,
        "recovery_hint": "none",
    }


def test_code_execution_result_supports_populated_error() -> None:
    """CodeExecutionResult supports a structured code error."""
    error = CodeError(name="ValueError", value="bad input", traceback="Traceback...")

    result = CodeExecutionResult(
        stdout="",
        stderr="warning",
        error=error,
        success=False,
        truncated=True,
        recovery_hint=RecoveryHint.RESET_RECOMMENDED,
    )

    assert result.error == error
    assert result.model_dump(mode="json")["error"] == {
        "name": "ValueError",
        "value": "bad input",
        "traceback": "Traceback...",
    }
    assert result.model_dump(mode="json")["recovery_hint"] == "reset_recommended"


def test_code_execution_result_rejects_error_when_successful() -> None:
    """Successful code execution results cannot contain an error."""
    error = CodeError(name="ValueError", value="bad input", traceback="Traceback...")

    with pytest.raises(ValueError, match="error must be None when success is True"):
        CodeExecutionResult(stdout="ok", error=error, success=True)


def test_code_execution_result_round_trips_from_json_dump() -> None:
    """CodeExecutionResult validates back from serialized JSON-mode data."""
    error = CodeError(name="RuntimeError", value="boom", traceback="Traceback...")
    original = CodeExecutionResult(
        stdout="partial",
        stderr="warning",
        error=error,
        success=False,
        truncated=True,
        recovery_hint=RecoveryHint.UNRECOVERABLE,
    )

    restored = CodeExecutionResult.model_validate(original.model_dump(mode="json"))

    assert restored == original
    assert restored.recovery_hint is RecoveryHint.UNRECOVERABLE
    assert restored.error == error


def test_shell_result_fields() -> None:
    """ShellResult stores shell execution output and status."""
    result = ShellResult(stdout="done", exit_code=0, success=True)

    assert result.stdout == "done"
    assert result.exit_code == 0
    assert result.success is True


def test_shell_result_rejects_success_mismatch() -> None:
    """ShellResult success must match the shell exit code."""
    with pytest.raises(ValueError, match="success must match exit_code"):
        ShellResult(stdout="failed", exit_code=1, success=True)

    with pytest.raises(ValueError, match="success must match exit_code"):
        ShellResult(stdout="done", exit_code=0, success=False)


def test_executor_status_wire_values_are_lowercase() -> None:
    """ExecutorStatus exposes lowercase wire values."""
    assert ExecutorStatus.NONE.value == "none"
    assert ExecutorStatus.CREATING.value == "creating"
    assert ExecutorStatus.READY.value == "ready"
    assert ExecutorStatus.FAILED.value == "failed"
    assert ExecutorStatus.CLEANED.value == "cleaned"
