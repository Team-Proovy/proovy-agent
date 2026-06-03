"""Planner hold and CreditSettler ledger wiring tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from langchain_core.messages import HumanMessage
import pytest

from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.emitter import SSEEmitter
from proovy_agent.features.credits import InsufficientCreditsError
from proovy_agent.features.credits.models import CreditHold, CreditHoldStatus
from proovy_agent.features.video.models import VideoJobStatus
from proovy_agent.graph.nodes import planner as planner_module
from proovy_agent.graph.nodes.credit_settler import credit_settler
from proovy_agent.graph.runtime import current_credit_ledger_client, current_video_job_client
from proovy_agent.graph.state import CreditEntry, ProovyState


class _FakeCreditLedger:
    def __init__(
        self,
        *,
        hold_id: UUID | None = None,
        hold_error: Exception | None = None,
        finalize_remaining: Decimal = Decimal("0"),
    ) -> None:
        self.hold_id = hold_id or uuid4()
        self.hold_error = hold_error
        self.finalize_remaining = finalize_remaining
        self.hold_calls: list[tuple[str, Decimal, str | None]] = []
        self.finalize_calls: list[tuple[str, UUID, Decimal]] = []
        self.release_calls: list[tuple[str, UUID]] = []

    async def hold(
        self,
        user_id: str,
        amount: Decimal,
        *,
        plan_id: str | None = None,
    ) -> CreditHold:
        self.hold_calls.append((user_id, amount, plan_id))
        if self.hold_error is not None:
            raise self.hold_error
        return _hold(self.hold_id, user_id, amount, CreditHoldStatus.PENDING, plan_id=plan_id)

    async def finalize_hold(
        self,
        user_id: str,
        hold_id: UUID,
        actual_amount: Decimal,
    ) -> CreditHold:
        self.finalize_calls.append((user_id, hold_id, actual_amount))
        return _hold(hold_id, user_id, self.finalize_remaining, CreditHoldStatus.CAPTURED)

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        self.release_calls.append((user_id, hold_id))
        return _hold(hold_id, user_id, Decimal("0"), CreditHoldStatus.RELEASED)


class _FakeVideoClient:
    def __init__(self, job: object | None, *, can_retry: bool) -> None:
        self.job = job
        self.can_retry_result = can_retry
        self.get_progress_calls: list[tuple[str, str | None]] = []

    async def get_progress(self, job_id: str, *, user_id: str | None = None) -> object | None:
        self.get_progress_calls.append((job_id, user_id))
        return self.job

    async def can_user_retry(self, _job: object) -> bool:
        return self.can_retry_result


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


def _mock_llm(result: object) -> MagicMock:
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result)
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _planner_output() -> planner_module._PlannerOutput:
    return planner_module._PlannerOutput(
        steps=[
            planner_module._StepInput(action="solve", description="수학 문제 풀이"),
            planner_module._StepInput(action="pdf", description="PDF 해설지 생성"),
        ],
        difficulty="easy",
        use_page=False,
        explanation_mode="full",
    )


async def _collect_events(emitter: SSEEmitter) -> list[dict]:
    await emitter.close()
    return [json.loads(event["data"]) async for event in emitter.stream()]


@pytest.mark.asyncio
async def test_plan_hold_to_solve_pdf_capture_refunds_estimate() -> None:
    hold_id = uuid4()
    ledger = _FakeCreditLedger(hold_id=hold_id, finalize_remaining=Decimal("20"))
    state = ProovyState(
        user_id="u",
        thread_id="t",
        messages=[HumanMessage(content="1+1을 풀고 PDF로 만들어줘")],
        credit_log=[CreditEntry(node="router", action="llm_call", model="flash", cost=1.0)],
    )

    token = current_credit_ledger_client.set(ledger)
    try:
        with patch(
            "proovy_agent.graph.nodes.planner.get_llm",
            return_value=_mock_llm(_planner_output()),
        ):
            planner_update = await planner_module.planner(state)

        assert planner_update["hold_id"] == str(hold_id)
        assert ledger.hold_calls == [("u", Decimal("20"), "t")]

        emitter = SSEEmitter(thread_id="t")
        emitter_token = current_emitter.set(emitter)
        try:
            settlement = await credit_settler(
                ProovyState(
                    user_id="u",
                    thread_id="t",
                    hold_id=str(hold_id),
                    credit_log=[
                        *state.credit_log,
                        *planner_update["credit_log"],
                        CreditEntry(node="core_solver", action="llm_call_verify", cost=2.0),
                        CreditEntry(node="pdf_node", action="pdf", cost=1.0),
                    ],
                )
            )
        finally:
            current_emitter.reset(emitter_token)

        assert ledger.finalize_calls == [("u", hold_id, Decimal("5"))]
        assert settlement["hold_id"] is None
        assert settlement["total_credit_cost"] == 5.0

        events = await _collect_events(emitter)
        credit_event = next(event for event in events if event["type"] == "credit_settled")
        assert credit_event["payload"]["actual"] == 5.0
        assert credit_event["payload"]["reserved"] == 20.0
        assert credit_event["payload"]["refunded"] == 15.0
    finally:
        current_credit_ledger_client.reset(token)


@pytest.mark.asyncio
async def test_planner_rejects_insufficient_credits_before_execution() -> None:
    ledger = _FakeCreditLedger(
        hold_error=InsufficientCreditsError(
            user_id="u",
            required=Decimal("20"),
            available=Decimal("3"),
        )
    )
    state = ProovyState(
        user_id="u",
        thread_id="t",
        messages=[HumanMessage(content="1+1을 풀고 PDF로 만들어줘")],
        credit_log=[CreditEntry(node="router", action="llm_call", model="flash", cost=1.0)],
    )
    emitter = SSEEmitter(thread_id="t")

    credit_token = current_credit_ledger_client.set(ledger)
    emitter_token = current_emitter.set(emitter)
    try:
        with (
            patch(
                "proovy_agent.graph.nodes.planner.get_llm",
                return_value=_mock_llm(_planner_output()),
            ),
            pytest.raises(planner_module.PlannerPreflightError),
        ):
            await planner_module.planner(state)
    finally:
        current_emitter.reset(emitter_token)
        current_credit_ledger_client.reset(credit_token)

    assert ledger.hold_calls == [("u", Decimal("20"), "t")]
    events = await _collect_events(emitter)
    error_event = next(event for event in events if event["type"] == "error")
    assert error_event["payload"]["code"] == "credit_exhausted"
    assert "20 cr 필요" in error_event["payload"]["message"]


@pytest.mark.asyncio
async def test_retry_preflight_failure_does_not_create_hold() -> None:
    stale_hold_id = uuid4()
    ledger = _FakeCreditLedger()
    video_client = _FakeVideoClient(
        SimpleNamespace(
            thread_id="t",
            status=VideoJobStatus.SUCCEEDED,
            retry_source_job_id=None,
        ),
        can_retry=False,
    )
    state = ProovyState(
        user_id="u",
        thread_id="t",
        hold_id=str(stale_hold_id),
        messages=[
            HumanMessage(
                content="이전 영상 다시 만들기",
                additional_kwargs={
                    "action": "video_retry",
                    "retry_source_job_id": "job-1",
                },
            )
        ],
    )

    credit_token = current_credit_ledger_client.set(ledger)
    video_token = current_video_job_client.set(video_client)
    try:
        with (
            patch("proovy_agent.graph.nodes.planner.get_llm") as get_llm,
            pytest.raises(planner_module.PlannerPreflightError),
        ):
            await planner_module.planner(state)
    finally:
        current_video_job_client.reset(video_token)
        current_credit_ledger_client.reset(credit_token)

    get_llm.assert_not_called()
    assert video_client.get_progress_calls == [("job-1", "u")]
    assert ledger.release_calls == [("u", stale_hold_id)]
    assert ledger.hold_calls == []


@pytest.mark.asyncio
async def test_retry_preflight_without_video_client_rejects_before_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _FakeCreditLedger()
    monkeypatch.setattr(planner_module.settings, "database_url", "")
    state = ProovyState(
        user_id="u",
        thread_id="t",
        messages=[
            HumanMessage(
                content="이전 영상 다시 만들기",
                additional_kwargs={
                    "action": "video_retry",
                    "retry_source_job_id": "job-1",
                },
            )
        ],
    )

    token = current_credit_ledger_client.set(ledger)
    try:
        with (
            patch("proovy_agent.graph.nodes.planner.get_llm") as get_llm,
            pytest.raises(planner_module.PlannerPreflightError),
        ):
            await planner_module.planner(state)
    finally:
        current_credit_ledger_client.reset(token)

    get_llm.assert_not_called()
    assert ledger.hold_calls == []


@pytest.mark.asyncio
async def test_planner_releases_stale_hold_before_new_plan_hold() -> None:
    stale_hold_id = uuid4()
    new_hold_id = uuid4()
    ledger = _FakeCreditLedger(hold_id=new_hold_id)
    state = ProovyState(
        user_id="u",
        thread_id="t",
        hold_id=str(stale_hold_id),
        messages=[HumanMessage(content="1+1을 풀고 PDF로 만들어줘")],
        credit_log=[CreditEntry(node="router", action="llm_call", model="flash", cost=1.0)],
    )

    token = current_credit_ledger_client.set(ledger)
    try:
        with patch(
            "proovy_agent.graph.nodes.planner.get_llm",
            return_value=_mock_llm(_planner_output()),
        ):
            update = await planner_module.planner(state)
    finally:
        current_credit_ledger_client.reset(token)

    assert ledger.release_calls == [("u", stale_hold_id)]
    assert ledger.hold_calls == [("u", Decimal("20"), "t")]
    assert update["hold_id"] == str(new_hold_id)


@pytest.mark.asyncio
async def test_planner_works_without_ledger_client_for_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(planner_module.settings, "database_url", "")
    state = ProovyState(
        user_id="u",
        thread_id="t",
        messages=[HumanMessage(content="1+1은?")],
    )

    with patch(
        "proovy_agent.graph.nodes.planner.get_llm",
        return_value=_mock_llm(_planner_output()),
    ):
        update = await planner_module.planner(state)

    assert update["hold_id"] is None
    assert [step.action for step in update["plan"]] == ["solve", "pdf"]
