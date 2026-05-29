"""Health endpoint tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from proovy_agent.app import main


@asynccontextmanager
async def _fake_checkpointer(_url: str) -> AsyncIterator[InMemorySaver]:
    """실제 Postgres 연결을 피하고 InMemorySaver로 격리."""
    yield InMemorySaver()


def test_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Health endpoint returns service status."""

    async def init_daytona_client() -> None:
        """Skip Daytona initialization for the health check test."""
        return None

    async def close_daytona_client() -> None:
        """Skip Daytona cleanup for the health check test."""
        return None

    monkeypatch.setattr(main, "init_daytona_client", init_daytona_client)
    monkeypatch.setattr(main, "close_daytona_client", close_daytona_client)
    app = main.create_app()
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_app_lifespan_initializes_and_closes_daytona(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App lifespan initializes and closes the shared Daytona client."""
    calls: list[str] = []

    async def init_daytona_client() -> None:
        """Record startup initialization."""
        calls.append("init")

    async def close_daytona_client() -> None:
        """Record shutdown cleanup."""
        calls.append("close")

    monkeypatch.setattr(main, "init_daytona_client", init_daytona_client)
    monkeypatch.setattr(main, "close_daytona_client", close_daytona_client)
    monkeypatch.setattr(main, "open_checkpointer", _fake_checkpointer)
    app = main.create_app()

    with TestClient(app):
        assert calls == ["init"]

    assert calls == ["init", "close"]
