"""POST /api/v1/solve SSE 엔드포인트 테스트."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from proovy_agent.app import main


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def noop() -> None:
        pass

    monkeypatch.setattr(main, "init_daytona_client", noop)
    monkeypatch.setattr(main, "close_daytona_client", noop)

    # 실제 Postgres 연결을 피하고 InMemorySaver로 격리 (.env에 database_url이 있어도)
    @asynccontextmanager
    async def fake_checkpointer(
        _url: str, *, allow_memory_fallback: bool = True
    ) -> AsyncIterator[InMemorySaver]:
        yield InMemorySaver()

    monkeypatch.setattr(main, "open_checkpointer", fake_checkpointer)
    return TestClient(main.create_app())


def test_missing_problem_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/solve", json={"user_id": "u"})
    assert response.status_code == 422


def test_user_id_with_colon_returns_422(client: TestClient) -> None:
    """user_id에 ':'가 있으면 체크포인트 키 충돌 위험으로 거부된다."""
    response = client.post(
        "/api/v1/solve",
        json={"problem": "1+1", "user_id": "a:b", "thread_id": "t"},
    )
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
    mock_graph.ainvoke.assert_awaited_once()


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
    mock_graph.ainvoke.assert_awaited_once()
    passed_state = mock_graph.ainvoke.call_args.args[0]
    assert passed_state.thread_id


def test_thread_id_namespaced_by_user_in_config(client: TestClient) -> None:
    """체크포인트 thread_id가 user_id로 네임스페이스되어 config로 넘어간다."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with patch("proovy_agent.app.api.v1.solve.get_graph", return_value=mock_graph):
        response = client.post(
            "/api/v1/solve",
            json={"problem": "테스트", "user_id": "u", "thread_id": "th-123"},
        )

    assert response.status_code == 200
    mock_graph.ainvoke.assert_awaited_once()
    config = mock_graph.ainvoke.call_args.kwargs.get("config")
    assert config == {"configurable": {"thread_id": "u:th-123"}}


def test_solve_configures_ping_heartbeat(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EventSourceResponse에 ping(하트비트) 간격이 설정된다 (§6.1)."""
    from proovy_agent.app.api.v1 import solve as solve_module

    captured: dict = {}
    real_esr = solve_module.EventSourceResponse

    def _spy(content: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return real_esr(content, **kwargs)

    monkeypatch.setattr(solve_module, "EventSourceResponse", _spy)

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    with patch.object(solve_module, "get_graph", return_value=mock_graph):
        response = client.post(
            "/api/v1/solve",
            json={"problem": "q", "user_id": "u"},
        )

    assert response.status_code == 200
    assert captured.get("ping") == 15
