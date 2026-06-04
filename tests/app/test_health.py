"""Health endpoint tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from proovy_agent.app import main


@asynccontextmanager
async def _fake_checkpointer(
    _url: str, *, allow_memory_fallback: bool = True
) -> AsyncIterator[InMemorySaver]:
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

    async def cancel_active_graph_tasks() -> None:
        calls.append("cancel_tasks")

    @asynccontextmanager
    async def open_credit_ledger_client(_settings: object) -> AsyncIterator[object | None]:
        yield None

    monkeypatch.setattr(main, "init_daytona_client", init_daytona_client)
    monkeypatch.setattr(main, "close_daytona_client", close_daytona_client)
    monkeypatch.setattr(main, "cancel_active_graph_tasks", cancel_active_graph_tasks)
    monkeypatch.setattr(main, "open_credit_ledger_client", open_credit_ledger_client)
    monkeypatch.setattr(main, "open_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(main, "create_video_job_client", lambda _settings: object())
    monkeypatch.setattr(
        main,
        "create_video_artifact_url_resolver",
        lambda _settings: object(),
    )
    app = main.create_app()

    with TestClient(app):
        assert calls == ["init"]

    assert calls == ["init", "cancel_tasks", "close"]


def test_app_lifespan_opens_and_closes_credit_ledger_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App lifespan keeps a pooled credit ledger client open for the app lifetime."""
    calls: list[str] = []
    credit_client = object()

    async def init_daytona_client() -> None:
        calls.append("init")

    async def close_daytona_client() -> None:
        calls.append("close")

    async def cancel_active_graph_tasks() -> None:
        calls.append("cancel_tasks")

    @asynccontextmanager
    async def open_credit_ledger_client(_settings: object) -> AsyncIterator[object]:
        calls.append("credit_open")
        try:
            yield credit_client
        finally:
            calls.append("credit_close")

    monkeypatch.setattr(main, "init_daytona_client", init_daytona_client)
    monkeypatch.setattr(main, "close_daytona_client", close_daytona_client)
    monkeypatch.setattr(main, "cancel_active_graph_tasks", cancel_active_graph_tasks)
    monkeypatch.setattr(main, "open_credit_ledger_client", open_credit_ledger_client)
    monkeypatch.setattr(main, "open_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(main, "create_video_job_client", lambda _settings: object())
    monkeypatch.setattr(
        main,
        "create_video_artifact_url_resolver",
        lambda _settings: object(),
    )
    app = main.create_app()

    with TestClient(app):
        assert app.state.credit_ledger_client is credit_client
        assert calls == ["init", "credit_open"]

    assert calls == ["init", "credit_open", "cancel_tasks", "credit_close", "close"]


def test_app_lifespan_closes_daytona_when_later_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daytona init 이후 startup 실패가 나도 shared client를 정리한다."""
    calls: list[str] = []

    async def init_daytona_client() -> None:
        calls.append("init")

    async def close_daytona_client() -> None:
        calls.append("close")

    def create_video_job_client(_settings: object) -> object:
        raise RuntimeError("video setup failed")

    @asynccontextmanager
    async def open_credit_ledger_client(_settings: object) -> AsyncIterator[object | None]:
        yield None

    monkeypatch.setattr(main, "init_daytona_client", init_daytona_client)
    monkeypatch.setattr(main, "close_daytona_client", close_daytona_client)
    monkeypatch.setattr(main, "open_credit_ledger_client", open_credit_ledger_client)
    monkeypatch.setattr(main, "create_video_job_client", create_video_job_client)

    with pytest.raises(RuntimeError, match="video setup failed"), TestClient(main.create_app()):
        pass

    assert calls == ["init", "close"]
