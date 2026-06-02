"""POST /stream/v2 + GET /health 백엔드 연동 어댑터 테스트.

백엔드(Proovy-server) 계약: 요청은 camelCase StreamInput, 응답은
`llm.token.delta`(delta 누적) + 종료 `run.completed`/`run.failed`, 어느 이벤트든
`data.thread_id` 포함. 내부 전용 이벤트(page_start 등)는 drop된다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
import pytest

from proovy_agent.app import main
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import PageStartPayload, TokenPayload
from proovy_agent.graph.state import PlanStep


def _parse_sse(text: str) -> list[dict]:
    """SSE 응답 텍스트를 프레임 리스트로 파싱한다 (event/id/data)."""
    frames: list[dict] = []
    text = text.replace("\r\n", "\n")
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        frame: dict = {}
        for line in block.splitlines():
            if line.startswith("data:"):
                frame["data"] = json.loads(line[len("data:") :].strip())
            elif line.startswith("event:"):
                frame["event"] = line[len("event:") :].strip()
            elif line.startswith("id:"):
                frame["id"] = line[len("id:") :].strip()
        if "data" in frame:
            frames.append(frame)
    return frames


class _ScriptedGraph:
    """ainvoke 시 current_emitter로 지정된 payload들을 순서대로 emit하는 가짜 그래프."""

    def __init__(self, payloads: list[BaseModel]) -> None:
        self._payloads = payloads

    async def ainvoke(self, _state: object, config: object | None = None) -> dict:
        emitter = current_emitter.get()
        assert emitter is not None
        for payload in self._payloads:
            await emitter.emit(payload)
        return {}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def noop() -> None:
        pass

    monkeypatch.setattr(main, "init_daytona_client", noop)
    monkeypatch.setattr(main, "close_daytona_client", noop)

    @asynccontextmanager
    async def fake_checkpointer(
        _url: str, *, allow_memory_fallback: bool = True
    ) -> AsyncIterator[InMemorySaver]:
        yield InMemorySaver()

    monkeypatch.setattr(main, "open_checkpointer", fake_checkpointer)
    return TestClient(main.create_app())


def _post_stream(client: TestClient, payloads: list[BaseModel], **body: object) -> list[dict]:
    req: dict = {"message": "q", "userId": "u", "threadId": "th-1"}
    req.update(body)
    with patch(
        "proovy_agent.app.api.stream.get_graph",
        return_value=_ScriptedGraph(payloads),
    ):
        response = client.post("/stream/v2", json=req)
    assert response.status_code == 200
    return _parse_sse(response.text)


def test_health_returns_ok(client: TestClient) -> None:
    """백엔드 사전 헬스체크 — 200."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_stream_v2_maps_tokens_and_completes(client: TestClient) -> None:
    """token → llm.token.delta, 종료 → run.completed. 모든 data에 thread_id."""
    frames = _post_stream(
        client,
        [TokenPayload(delta="정답은 "), TokenPayload(delta="42", final=True)],
    )

    events = [f["event"] for f in frames]
    assert events == ["llm.token.delta", "llm.token.delta", "run.completed"]

    # 토큰 프레임: delta + thread_id
    assert frames[0]["data"] == {"delta": "정답은 ", "thread_id": "th-1"}
    assert frames[1]["data"] == {"delta": "42", "thread_id": "th-1"}
    # 종료 프레임: thread_id만
    assert frames[-1]["data"] == {"thread_id": "th-1"}
    # 모든 프레임에 thread_id 존재 (백엔드가 첫 턴 영속화에 사용)
    assert all(f["data"].get("thread_id") == "th-1" for f in frames)


def test_stream_v2_drops_internal_only_events(client: TestClient) -> None:
    """page_start 등 백엔드가 소비 안 하는 내부 이벤트는 스트림에서 drop된다."""
    frames = _post_stream(
        client,
        [
            PageStartPayload(
                plan=[PlanStep(action="solve", description="x")],
                selected_model="flash",
                difficulty="easy",
                route="math_task",
                use_page=True,
            ),
            TokenPayload(delta="hi"),
        ],
    )
    events = [f["event"] for f in frames]
    # page_start는 빠지고 token + 종료만 남는다
    assert events == ["llm.token.delta", "run.completed"]


def test_stream_v2_accepts_camelcase_and_autogenerates_thread_id(
    client: TestClient,
) -> None:
    """threadId 미전송 시 새 thread 생성 + 모든 data에 echo (camelCase 수용)."""
    with patch(
        "proovy_agent.app.api.stream.get_graph",
        return_value=_ScriptedGraph([TokenPayload(delta="x")]),
    ):
        response = client.post(
            "/stream/v2",
            json={"message": "테스트", "userId": "u"},  # threadId 없음
        )
    assert response.status_code == 200
    frames = _parse_sse(response.text)
    tid = frames[0]["data"]["thread_id"]
    assert tid  # 자동 생성됨
    assert all(f["data"]["thread_id"] == tid for f in frames)


def test_stream_v2_graph_exception_maps_to_run_failed(client: TestClient) -> None:
    """그래프 예외 시 마지막 이벤트는 run.failed (data.message), run.completed 없음."""

    class _BoomGraph:
        async def ainvoke(self, _state: object, config: object | None = None) -> dict:
            raise RuntimeError("boom")

    with patch("proovy_agent.app.api.stream.get_graph", return_value=_BoomGraph()):
        response = client.post(
            "/stream/v2", json={"message": "q", "userId": "u", "threadId": "th-1"}
        )
    assert response.status_code == 200
    frames = _parse_sse(response.text)

    events = [f["event"] for f in frames]
    assert events == ["run.failed"]
    assert "run.completed" not in events
    assert frames[-1]["data"]["message"] == "풀이 중 오류가 발생했습니다."
    assert frames[-1]["data"]["thread_id"] == "th-1"


def test_stream_v2_user_id_with_colon_returns_422(client: TestClient) -> None:
    """userId에 ':'가 있으면 체크포인트 키 충돌 위험으로 거부된다."""
    response = client.post(
        "/stream/v2",
        json={"message": "1+1", "userId": "a:b", "threadId": "t"},
    )
    assert response.status_code == 422


def test_stream_v2_missing_message_returns_422(client: TestClient) -> None:
    response = client.post("/stream/v2", json={"userId": "u"})
    assert response.status_code == 422


def test_stream_v2_missing_user_id_returns_422(client: TestClient) -> None:
    """userId 생략 시 422 — 빈 user_id면 체크포인트 키가 충돌(멀티턴 누수)."""
    response = client.post("/stream/v2", json={"message": "1+1"})
    assert response.status_code == 422


def test_stream_v2_empty_user_id_returns_422(client: TestClient) -> None:
    """빈 문자열 userId도 거부."""
    response = client.post("/stream/v2", json={"message": "1+1", "userId": ""})
    assert response.status_code == 422


def test_stream_v2_accepts_null_optional_fields(client: TestClient) -> None:
    """백엔드(Jackson)가 미선택 필드를 null로 보내도 422가 아니라 정상 처리한다.

    기능 미선택 일반 요청은 chosenFeatures 등이 null로 직렬화되는데, 이게 422면
    AI /stream/v2 경계에서 일반 요청이 깨진다(백엔드 계약 호환성).
    """
    with patch(
        "proovy_agent.app.api.stream.get_graph",
        return_value=_ScriptedGraph([TokenPayload(delta="x")]),
    ):
        response = client.post(
            "/stream/v2",
            json={
                "message": "q",
                "userId": "u",
                "threadId": "th-1",
                "chosenFeatures": None,
                "filesUrl": None,
                "agentConfig": None,
                "streamTokens": None,
            },
        )
    assert response.status_code == 200
    events = [f["event"] for f in _parse_sse(response.text)]
    assert events == ["llm.token.delta", "run.completed"]
