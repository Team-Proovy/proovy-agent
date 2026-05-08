"""Health endpoint tests."""

from fastapi.testclient import TestClient

from proovy_agent.app.main import app


def test_health_check() -> None:
    """Health endpoint returns service status."""
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
