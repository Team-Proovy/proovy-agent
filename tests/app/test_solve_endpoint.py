"""POST /api/v1/solve SSE 엔드포인트 테스트."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from proovy_agent.app import main


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def noop() -> None:
        pass

    monkeypatch.setattr(main, "init_daytona_client", noop)
    monkeypatch.setattr(main, "close_daytona_client", noop)
    return TestClient(main.create_app())


def test_missing_problem_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/solve", json={"user_id": "u"})
    assert response.status_code == 422


def test_missing_user_id_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/solve", json={"problem": "1+1"})
    assert response.status_code == 422


def test_valid_request_returns_sse_stream(client: TestClient) -> None:
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with patch("proovy_agent.app.api.v1.solve.get_graph", return_value=mock_graph):
        response = client.post(
            "/api/v1/solve",
            json={"problem": "1+1은?", "user_id": "test"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_thread_id_auto_generated(client: TestClient) -> None:
    """thread_id 미전달 시 자동 생성된다."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with patch("proovy_agent.app.api.v1.solve.get_graph", return_value=mock_graph):
        response = client.post(
            "/api/v1/solve",
            json={"problem": "테스트", "user_id": "u"},
        )

    assert response.status_code == 200
