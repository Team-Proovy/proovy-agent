"""Shared Daytona client lifecycle tests."""

import pytest

from proovy_agent.common.config import settings
from proovy_agent.common.sandbox import client


class FakeDaytonaConfig:
    """Capture Daytona configuration values."""

    def __init__(self, api_key: str, api_url: str, target: str | None) -> None:
        """Store provided Daytona configuration values."""
        self.api_key = api_key
        self.api_url = api_url
        self.target = target


class FakeAsyncDaytona:
    """Fake async Daytona client."""

    def __init__(self, config: FakeDaytonaConfig) -> None:
        """Store config and initialize close tracking."""
        self.config = config
        self.closed = False

    async def close(self) -> None:
        """Mark the fake client as closed."""
        self.closed = True


@pytest.fixture(autouse=True)
async def reset_client() -> None:
    """Reset singleton state between tests."""
    client._client = None
    yield
    client._client = None


def test_get_daytona_client_raises_when_not_initialized() -> None:
    """Client access before startup raises a clear error."""
    with pytest.raises(RuntimeError, match="Daytona client not initialized"):
        client.get_daytona_client()


async def test_init_get_close_get_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Client initializes from settings, returns singleton, and clears on close."""
    monkeypatch.setattr(client, "DaytonaConfig", FakeDaytonaConfig)
    monkeypatch.setattr(client, "AsyncDaytona", FakeAsyncDaytona)

    await client.init_daytona_client()

    daytona_client = client.get_daytona_client()
    assert isinstance(daytona_client, FakeAsyncDaytona)
    assert daytona_client.config.api_key == settings.daytona_api_key
    assert daytona_client.config.api_url == settings.daytona_api_url
    assert daytona_client.config.target == settings.daytona_target

    await client.close_daytona_client()

    assert daytona_client.closed is True
    with pytest.raises(RuntimeError, match="Daytona client not initialized"):
        client.get_daytona_client()

    await client.init_daytona_client()

    reinitialized_client = client.get_daytona_client()
    assert isinstance(reinitialized_client, FakeAsyncDaytona)
    assert reinitialized_client is not daytona_client
    await client.close_daytona_client()
    assert reinitialized_client.closed is True


async def test_init_daytona_client_keeps_existing_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated initialization keeps the existing shared client."""
    monkeypatch.setattr(client, "DaytonaConfig", FakeDaytonaConfig)
    monkeypatch.setattr(client, "AsyncDaytona", FakeAsyncDaytona)
    await client.init_daytona_client()
    existing_client = client.get_daytona_client()

    await client.init_daytona_client()

    assert client.get_daytona_client() is existing_client
    assert existing_client.closed is False


async def test_close_daytona_client_noop_when_not_initialized() -> None:
    """Closing without an initialized client is safe."""
    await client.close_daytona_client()

    assert client._client is None


async def test_close_daytona_client_awaits_close_and_clears_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing awaits the SDK client close method and clears shared state."""
    monkeypatch.setattr(client, "DaytonaConfig", FakeDaytonaConfig)
    monkeypatch.setattr(client, "AsyncDaytona", FakeAsyncDaytona)
    await client.init_daytona_client()
    daytona_client = client.get_daytona_client()

    await client.close_daytona_client()

    assert daytona_client.closed is True
    assert client._client is None


async def test_close_daytona_client_clears_singleton_when_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing clears shared state even when the SDK client close fails."""

    class FailingCloseAsyncDaytona(FakeAsyncDaytona):
        async def close(self) -> None:
            """Mark closed and simulate SDK close failure."""
            self.closed = True
            raise RuntimeError("close failed")

    monkeypatch.setattr(client, "DaytonaConfig", FakeDaytonaConfig)
    monkeypatch.setattr(client, "AsyncDaytona", FailingCloseAsyncDaytona)
    await client.init_daytona_client()
    failed_client = client.get_daytona_client()

    await client.close_daytona_client()

    assert failed_client.closed is True
    assert client._client is None

    monkeypatch.setattr(client, "AsyncDaytona", FakeAsyncDaytona)
    await client.init_daytona_client()
    assert client.get_daytona_client() is not failed_client
