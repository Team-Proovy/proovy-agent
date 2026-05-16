"""Sandbox public API tests."""

from proovy_agent.common import sandbox


def test_sandbox_module_exports_full_public_api() -> None:
    expected_names = {
        "CodeError",
        "CodeExecutionError",
        "CodeExecutionResult",
        "CodeExecutor",
        "ExecutorStatus",
        "RecoveryHint",
        "RequestExecutorContext",
        "SandboxConfig",
        "SandboxCreationError",
        "SandboxError",
        "SandboxManager",
        "SandboxTimeoutError",
        "SandboxUnavailableError",
        "ShellResult",
        "close_daytona_client",
        "get_daytona_client",
        "get_whitelisted_preamble",
        "init_daytona_client",
    }

    assert set(sandbox.__all__) == expected_names

    for name in expected_names:
        assert getattr(sandbox, name) is not None
