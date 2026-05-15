"""Health endpoint tests."""

from fastapi.testclient import TestClient
import pytest

from proovy_agent.app import main


def test_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Health endpoint returns service status."""

    async def init_daytona_client() -> None:
        return None

    async def close_daytona_client() -> None:
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
        calls.append("init")

    async def close_daytona_client() -> None:
        calls.append("close")

    monkeypatch.setattr(main, "init_daytona_client", init_daytona_client)
    monkeypatch.setattr(main, "close_daytona_client", close_daytona_client)
    app = main.create_app()

    with TestClient(app):
        assert calls == ["init"]

    assert calls == ["init", "close"]
