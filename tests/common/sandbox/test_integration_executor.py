"""Daytona CodeExecutor integration tests."""

from __future__ import annotations

import os

import pytest

from proovy_agent.common.config import settings
from proovy_agent.common.sandbox import (
    RecoveryHint,
    SandboxConfig,
    SandboxManager,
    SandboxTimeoutError,
    close_daytona_client,
    get_daytona_client,
    init_daytona_client,
)


def _has_daytona_env() -> bool:
    return bool(os.getenv("DAYTONA_API_KEY") and os.getenv("DAYTONA_SNAPSHOT"))


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _has_daytona_env(),
        reason="Daytona integration tests require DAYTONA_API_KEY and DAYTONA_SNAPSHOT",
    ),
]


@pytest.fixture
async def executor():
    await init_daytona_client()
    client = get_daytona_client()
    config = SandboxConfig.from_settings(settings)
    manager = SandboxManager(client)
    executor = await manager.create_executor("integration-thread", config=config)

    try:
        yield executor
    finally:
        await manager.destroy_executor(executor)
        await close_daytona_client()


async def test_run_python_prints_basic_output(executor) -> None:
    result = await executor.run_python("print(1 + 1)")

    assert result.success is True
    assert result.stdout.strip() == "2"
    assert result.stderr == ""
    assert result.error is None
    assert result.recovery_hint is RecoveryHint.NONE
    assert result.truncated is False


async def test_run_python_preserves_context_between_runs(executor) -> None:
    first = await executor.run_python("x = 41")
    second = await executor.run_python("print(x + 1)")

    assert first.success is True
    assert second.success is True
    assert second.stdout.strip() == "42"
    assert second.error is None


async def test_run_python_returns_zero_division_code_error(executor) -> None:
    result = await executor.run_python("1 / 0")

    assert result.success is False
    assert result.error is not None
    assert result.error.name == "ZeroDivisionError"
    assert result.recovery_hint is RecoveryHint.NONE


async def test_run_python_translates_timeout_exception(executor) -> None:
    with pytest.raises(SandboxTimeoutError):
        await executor.run_python("while True: pass", timeout=1)


async def test_run_python_truncates_stdout_when_limit_is_exceeded(executor) -> None:
    original_limit = executor._max_output_chars
    executor._max_output_chars = 20

    try:
        result = await executor.run_python("print('abcdefghijklmnopqrstuvwxyz')")
    finally:
        executor._max_output_chars = original_limit

    assert result.success is True
    assert result.truncated is True
    assert result.stdout == "abcdefghijklmnopqrst... [output truncated to 20 chars]"


async def test_reset_context_clears_user_state(executor) -> None:
    seeded = await executor.run_python("x = 41")
    await executor.reset_context()
    result = await executor.run_python("print(x)")

    assert seeded.success is True
    assert result.success is False
    assert result.error is not None
    assert result.error.name == "NameError"
    assert result.recovery_hint is RecoveryHint.RESET_RECOMMENDED
