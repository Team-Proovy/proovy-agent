"""POST /api/v1/solve SSE 엔드포인트 테스트."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, TypeAdapter
import pytest

from proovy_agent.app import main
from proovy_agent.app.api.v1 import solve as solve_module
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import (
    PageStartPayload,
    SSEEvent,
    TokenPayload,
)
from proovy_agent.features.credits.models import CreditHold, CreditHoldStatus
from proovy_agent.graph.runtime import current_credit_ledger_client
from proovy_agent.graph.state import PlanStep


def _parse_sse(text: str) -> list[dict]:
    """SSE 응답 텍스트를 프레임 리스트로 파싱한다 (event/id/data)."""
    frames: list[dict] = []
    text = text.replace("\r\n", "\n")  # SSE 프레임 구분자는 CRLF — LF로 정규화
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


class _FakeCreditLedger:
    def __init__(self, hold_id: UUID | None = None) -> None:
        self.hold_id = hold_id or uuid4()
        self.hold_calls: list[tuple[str, Decimal, str | None]] = []
        self.release_calls: list[tuple[str, UUID]] = []

    async def hold(
        self,
        user_id: str,
        amount: Decimal,
        *,
        plan_id: str | None = None,
    ) -> CreditHold:
        self.hold_calls.append((user_id, amount, plan_id))
        return _hold(self.hold_id, user_id, amount, CreditHoldStatus.PENDING, plan_id=plan_id)

    async def finalize_hold(
        self,
        user_id: str,
        hold_id: UUID,
        actual_amount: Decimal,
    ) -> CreditHold:
        return _hold(hold_id, user_id, actual_amount, CreditHoldStatus.CAPTURED)

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        self.release_calls.append((user_id, hold_id))
        return _hold(hold_id, user_id, Decimal("0"), CreditHoldStatus.RELEASED)


def _hold(
    hold_id: UUID,
    user_id: str,
    amount: Decimal,
    status: CreditHoldStatus,
    *,
    plan_id: str | None = None,
) -> CreditHold:
    now = datetime.now(UTC)
    return CreditHold(
        id=hold_id,
        user_id=user_id,
        amount=amount,
        status=status,
        created_at=now,
        expires_at=now + timedelta(minutes=20),
        plan_id=plan_id,
    )


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


# ── SSE envelope e2e (#61) ───────────────────────────────────────────────────


def _post(client: TestClient, payloads: list[BaseModel]) -> list[dict]:
    with patch(
        "proovy_agent.app.api.v1.solve.get_graph",
        return_value=_ScriptedGraph(payloads),
    ):
        response = client.post(
            "/api/v1/solve",
            json={"problem": "q", "user_id": "u", "thread_id": "th-1"},
        )
    assert response.status_code == 200
    return _parse_sse(response.text)


def test_solve_streams_envelope_sequence(client: TestClient) -> None:
    """page_start → token → done 순서 + envelope 메타·seq·id 형식 검증."""
    frames = _post(
        client,
        [
            PageStartPayload(
                plan=[PlanStep(action="solve", description="x")],
                selected_model="flash",
                difficulty="easy",
                route="math_task",
                use_page=True,
            ),
            TokenPayload(delta="42"),
        ],
    )

    types = [f["data"]["type"] for f in frames]
    assert types == ["page_start", "token", "done"]

    # seq 0부터 단조 증가
    assert [f["data"]["seq"] for f in frames] == [0, 1, 2]

    # 모든 프레임: 공통 메타 존재 + event 헤더 = type + id = <thread_id>:<seq>
    for f in frames:
        data = f["data"]
        assert {"type", "thread_id", "seq", "ts", "payload"} <= data.keys()
        assert data["thread_id"] == "th-1"
        assert f["event"] == data["type"]
        assert f["id"] == f"{data['thread_id']}:{data['seq']}"


def test_solve_envelopes_parse_through_discriminated_union(client: TestClient) -> None:
    """스트림된 각 envelope이 discriminated union으로 올바른 클래스로 역직렬화된다."""
    frames = _post(client, [TokenPayload(delta="hi")])
    adapter: TypeAdapter = TypeAdapter(SSEEvent)

    for f in frames:
        event = adapter.validate_python(f["data"])
        assert event.type == f["data"]["type"]

    token_frame = next(f for f in frames if f["data"]["type"] == "token")
    token_event = adapter.validate_python(token_frame["data"])
    assert token_event.payload.delta == "hi"


def test_solve_last_event_is_done_on_success(client: TestClient) -> None:
    """성공 시 마지막 이벤트는 done."""
    frames = _post(client, [])
    assert frames[-1]["data"]["type"] == "done"
    assert frames[-1]["data"]["payload"] == {"final": True}


def test_solve_emits_error_and_no_done_on_exception(client: TestClient) -> None:
    """그래프 예외 시 error를 보내고 done은 보내지 않는다."""

    class _BoomGraph:
        async def ainvoke(self, _state: object, config: object | None = None) -> dict:
            raise RuntimeError("boom")

    with patch("proovy_agent.app.api.v1.solve.get_graph", return_value=_BoomGraph()):
        response = client.post(
            "/api/v1/solve",
            json={"problem": "q", "user_id": "u", "thread_id": "th-1"},
        )
    assert response.status_code == 200
    frames = _parse_sse(response.text)

    # _BoomGraph는 emit 전에 raise → error 단 1개, done 없음
    types = [f["data"]["type"] for f in frames]
    assert types == ["error"]
    payload = frames[-1]["data"]["payload"]
    assert payload["code"] == "internal_error"
    assert payload["message"] == "풀이 중 오류가 발생했습니다."


def test_solve_releases_active_hold_on_graph_exception() -> None:
    """hold 생성 후 그래프가 실패하면 pending hold를 즉시 release한다."""
    ledger = _FakeCreditLedger()
    app = main.create_app()
    app.state.credit_ledger_client = ledger

    class _HoldThenBoomGraph:
        async def ainvoke(self, _state: object, config: object | None = None) -> dict:
            runtime_ledger = current_credit_ledger_client.get()
            assert runtime_ledger is not None
            await runtime_ledger.hold("u", Decimal("20"), plan_id="th-1")
            raise RuntimeError("boom")

    test_client = TestClient(app)
    with patch("proovy_agent.app.api.v1.solve.get_graph", return_value=_HoldThenBoomGraph()):
        response = test_client.post(
            "/api/v1/solve",
            json={"problem": "q", "user_id": "u", "thread_id": "th-1"},
        )

    assert response.status_code == 200
    frames = _parse_sse(response.text)
    assert [f["data"]["type"] for f in frames] == ["error"]
    assert ledger.hold_calls == [("u", Decimal("20"), "th-1")]
    assert ledger.release_calls == [("u", ledger.hold_id)]


@pytest.mark.asyncio
async def test_cancel_active_solve_tasks_cancels_and_awaits_registered_tasks() -> None:
    cleanup: list[str] = []
    ready = asyncio.Event()

    async def _sleeping_task() -> None:
        try:
            ready.set()
            await asyncio.Event().wait()
        finally:
            cleanup.append("done")

    task = asyncio.create_task(_sleeping_task())
    solve_module._active_tasks.add(task)
    task.add_done_callback(solve_module._active_tasks.discard)
    try:
        await ready.wait()

        await solve_module.cancel_active_solve_tasks()

        assert task.done()
        assert cleanup == ["done"]
        assert task not in solve_module._active_tasks
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        solve_module._active_tasks.discard(task)
