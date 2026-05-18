"""SandboxManager 테스트."""

from __future__ import annotations

import asyncio

import pytest

from proovy_agent.common.config import settings
from proovy_agent.common.sandbox import manager
from proovy_agent.common.sandbox.exceptions import SandboxCreationError
from proovy_agent.common.sandbox.models import SandboxConfig


class FakeCreateSandboxFromSnapshotParams:
    def __init__(
        self,
        snapshot: str,
        labels: dict[str, str],
        auto_stop_interval: int,
        network_block_all: bool,
    ) -> None:
        self.snapshot = snapshot
        self.labels = labels
        self.auto_stop_interval = auto_stop_interval
        self.network_block_all = network_block_all


class FakeSandbox:
    def __init__(self, events: list[str] | None = None) -> None:
        self.deleted = False
        self.events = events

    async def delete(self) -> None:
        self.deleted = True
        if self.events is not None:
            self.events.append("sandbox.delete")


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
        events: list[str] | None = None,
    ) -> None:
        self._sandbox = sandbox
        self.code_timeout = code_timeout
        self.max_output_chars = max_output_chars
        self.preamble_code = preamble_code
        self.cleaned = False
        self.events = events

    @property
    def sandbox(self) -> FakeSandbox:
        return self._sandbox

    async def cleanup(self) -> None:
        self.cleaned = True
        if self.events is not None:
            self.events.append("executor.cleanup")


@pytest.fixture(autouse=True)
def fake_daytona_types(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert params.auto_stop_interval == 15
    assert params.network_block_all is False


async def test_create_executor_does_not_pass_unsupported_snapshot_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StrictSnapshotParams:
        def __init__(
            self,
            *,
            snapshot: str,
            labels: dict[str, str],
            auto_stop_interval: int,
            network_block_all: bool,
        ) -> None:
            self.snapshot = snapshot
            self.labels = labels
            self.auto_stop_interval = auto_stop_interval
            self.network_block_all = network_block_all

    class StrictClient:
        def __init__(self) -> None:
            self.created_params: list[StrictSnapshotParams] = []
            self.sandbox = FakeSandbox()

        async def create(self, params: StrictSnapshotParams) -> FakeSandbox:
            self.created_params.append(params)
            return self.sandbox

    monkeypatch.setattr(manager, "CreateSandboxFromSnapshotParams", StrictSnapshotParams)
    client = StrictClient()
    sandbox_manager = manager.SandboxManager(client)
    config = SandboxConfig(snapshot="custom-snapshot", cpu=8, memory=16, disk=30)

    await sandbox_manager.create_executor("thread-with-resources", config=config)

    params = client.created_params[0]
    assert params.snapshot == "custom-snapshot"
    assert params.labels == {"thread_id": "thread-with-resources"}
    assert params.auto_stop_interval == 5
    assert params.network_block_all is True


async def test_create_executor_converts_sdk_errors_to_sandbox_creation_error() -> None:
    class FailingClient(FakeClient):
        async def create(self, params: FakeCreateSandboxFromSnapshotParams) -> FakeSandbox:
            raise RuntimeError("sdk down")

    sandbox_manager = manager.SandboxManager(FailingClient())

    with pytest.raises(SandboxCreationError, match="Sandbox 생성 실패") as exc_info:
        await sandbox_manager.create_executor("thread-123")

    assert isinstance(exc_info.value.__cause__, RuntimeError)


async def test_destroy_executor_cleans_up_then_deletes_sandbox() -> None:
    events: list[str] = []
    sandbox = FakeSandbox(events)
    executor = FakeCodeExecutor(sandbox, 60, 10_000, "", events)
    sandbox_manager = manager.SandboxManager(FakeClient())

    await sandbox_manager.destroy_executor(executor)

    assert executor.cleaned is True
    assert sandbox.deleted is True
    assert events == ["executor.cleanup", "sandbox.delete"]


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
        def __init__(
            self,
            sandbox: FakeSandbox,
            code_timeout: int,
            max_output_chars: int,
            preamble_code: str,
        ) -> None:
            super().__init__(sandbox, code_timeout, max_output_chars, preamble_code)
            self.cleanup_started = False

        async def cleanup(self) -> None:
            self.cleanup_started = True
            await asyncio.sleep(60)
            self.cleaned = True

    sandbox = FakeSandbox()
    executor = SlowCleanupExecutor(sandbox, 60, 10_000, "")
    sandbox_manager = manager.SandboxManager(FakeClient())

    await sandbox_manager.destroy_executor(executor, timeout=0.01)

    assert executor.cleanup_started is True
    assert executor.cleaned is False
    assert sandbox.deleted is True


async def test_destroy_executor_finishes_delete_when_cancelled_mid_delete() -> None:
    class SlowDeleteSandbox(FakeSandbox):
        def __init__(self) -> None:
            super().__init__()
            self.delete_started = asyncio.Event()
            self.delete_can_finish = asyncio.Event()
            self.delete_completed = False

        async def delete(self) -> None:
            self.deleted = True
            self.delete_started.set()
            await self.delete_can_finish.wait()
            self.delete_completed = True

    sandbox = SlowDeleteSandbox()
    executor = FakeCodeExecutor(sandbox, 60, 10_000, "")
    sandbox_manager = manager.SandboxManager(FakeClient())

    task = asyncio.create_task(sandbox_manager.destroy_executor(executor))
    await sandbox.delete_started.wait()

    task.cancel()
    sandbox.delete_can_finish.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert sandbox.deleted is True
    assert sandbox.delete_completed is True
