"""SandboxManager tests."""

from __future__ import annotations

import asyncio

import pytest

from proovy_agent.common.config import settings
from proovy_agent.common.sandbox import manager
from proovy_agent.common.sandbox.exceptions import SandboxCreationError
from proovy_agent.common.sandbox.models import SandboxConfig


class FakeResources:
    def __init__(self, cpu: int, memory: int, disk: int) -> None:
        self.cpu = cpu
        self.memory = memory
        self.disk = disk


class FakeCreateSandboxFromSnapshotParams:
    def __init__(
        self,
        snapshot: str,
        labels: dict[str, str],
        resources: FakeResources,
        auto_stop_interval: int,
        network_block_all: bool,
    ) -> None:
        self.snapshot = snapshot
        self.labels = labels
        self.resources = resources
        self.auto_stop_interval = auto_stop_interval
        self.network_block_all = network_block_all


class FakeSandbox:
    def __init__(self) -> None:
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeClient:
    def __init__(self, sandbox: FakeSandbox | None = None) -> None:
        self.sandbox = sandbox or FakeSandbox()
        self.created_params: list[FakeCreateSandboxFromSnapshotParams] = []

    async def create(self, params: FakeCreateSandboxFromSnapshotParams) -> FakeSandbox:
        self.created_params.append(params)
        return self.sandbox


class FakeCodeExecutor:
    def __init__(
        self,
        sandbox: FakeSandbox,
        code_timeout: int,
        max_output_chars: int,
        preamble_code: str,
    ) -> None:
        self._sandbox = sandbox
        self.code_timeout = code_timeout
        self.max_output_chars = max_output_chars
        self.preamble_code = preamble_code
        self.cleaned = False

    @property
    def sandbox(self) -> FakeSandbox:
        return self._sandbox

    async def cleanup(self) -> None:
        self.cleaned = True


@pytest.fixture(autouse=True)
def fake_daytona_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager, "Resources", FakeResources)
    monkeypatch.setattr(
        manager, "CreateSandboxFromSnapshotParams", FakeCreateSandboxFromSnapshotParams
    )
    monkeypatch.setattr(manager, "CodeExecutor", FakeCodeExecutor)


async def test_create_executor_uses_default_config_from_settings() -> None:
    sandbox = FakeSandbox()
    client = FakeClient(sandbox)
    sandbox_manager = manager.SandboxManager(client)

    executor = await sandbox_manager.create_executor("thread-123")

    assert isinstance(executor, FakeCodeExecutor)
    assert executor.sandbox is sandbox
    assert executor.code_timeout == settings.daytona_code_timeout
    assert executor.max_output_chars == settings.daytona_max_output_chars
    assert executor.preamble_code == "import sympy\nimport numpy as np\nimport scipy\n"

    assert len(client.created_params) == 1
    params = client.created_params[0]
    assert params.snapshot == settings.daytona_snapshot
    assert params.labels == {"thread_id": "thread-123"}
    assert params.resources.cpu == settings.daytona_sandbox_cpu
    assert params.resources.memory == settings.daytona_sandbox_memory
    assert params.resources.disk == settings.daytona_sandbox_disk
    assert params.auto_stop_interval == settings.daytona_auto_stop_interval
    assert params.network_block_all is True


async def test_create_executor_accepts_explicit_config() -> None:
    client = FakeClient()
    sandbox_manager = manager.SandboxManager(client)
    config = SandboxConfig(
        snapshot="custom-snapshot",
        cpu=4,
        memory=8,
        disk=20,
        auto_stop_interval=15,
        code_timeout=120,
        max_output_chars=1234,
        network_block_all=False,
        preamble_code="import math\n",
    )

    executor = await sandbox_manager.create_executor("custom-thread", config=config)

    assert executor.code_timeout == 120
    assert executor.max_output_chars == 1234
    assert executor.preamble_code == "import math\n"

    params = client.created_params[0]
    assert params.snapshot == "custom-snapshot"
    assert params.labels == {"thread_id": "custom-thread"}
    assert params.resources.cpu == 4
    assert params.resources.memory == 8
    assert params.resources.disk == 20
    assert params.auto_stop_interval == 15
    assert params.network_block_all is False


async def test_create_executor_converts_sdk_errors_to_sandbox_creation_error() -> None:
    class FailingClient(FakeClient):
        async def create(self, params: FakeCreateSandboxFromSnapshotParams) -> FakeSandbox:
            raise RuntimeError("sdk down")

    sandbox_manager = manager.SandboxManager(FailingClient())

    with pytest.raises(SandboxCreationError, match="Sandbox creation failed") as exc_info:
        await sandbox_manager.create_executor("thread-123")

    assert isinstance(exc_info.value.__cause__, RuntimeError)


async def test_destroy_executor_cleans_up_then_deletes_sandbox() -> None:
    sandbox = FakeSandbox()
    executor = FakeCodeExecutor(sandbox, 60, 10_000, "")
    sandbox_manager = manager.SandboxManager(FakeClient())

    await sandbox_manager.destroy_executor(executor)

    assert executor.cleaned is True
    assert sandbox.deleted is True


async def test_destroy_executor_deletes_sandbox_when_cleanup_fails() -> None:
    class CleanupFailingExecutor(FakeCodeExecutor):
        async def cleanup(self) -> None:
            self.cleaned = True
            raise RuntimeError("cleanup failed")

    sandbox = FakeSandbox()
    executor = CleanupFailingExecutor(sandbox, 60, 10_000, "")
    sandbox_manager = manager.SandboxManager(FakeClient())

    await sandbox_manager.destroy_executor(executor)

    assert executor.cleaned is True
    assert sandbox.deleted is True


async def test_destroy_executor_suppresses_delete_failure() -> None:
    class DeleteFailingSandbox(FakeSandbox):
        async def delete(self) -> None:
            self.deleted = True
            raise RuntimeError("delete failed")

    sandbox = DeleteFailingSandbox()
    executor = FakeCodeExecutor(sandbox, 60, 10_000, "")
    sandbox_manager = manager.SandboxManager(FakeClient())

    await sandbox_manager.destroy_executor(executor)

    assert executor.cleaned is True
    assert sandbox.deleted is True


async def test_destroy_executor_outer_timeout_returns_without_raising() -> None:
    class SlowCleanupExecutor(FakeCodeExecutor):
        async def cleanup(self) -> None:
            await asyncio.sleep(60)

    sandbox = FakeSandbox()
    executor = SlowCleanupExecutor(sandbox, 60, 10_000, "")
    sandbox_manager = manager.SandboxManager(FakeClient())

    await sandbox_manager.destroy_executor(executor, timeout=0.01)
