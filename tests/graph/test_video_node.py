"""VideoNode Mode B launcher tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from proovy_agent.features.credits.models import CreditHold, CreditHoldStatus
from proovy_agent.features.video.hint_extractor import HintExtractionResult
from proovy_agent.features.video.jobs import VideoCreditCapture
from proovy_agent.features.video.jobs.repository import (
    RetryAlreadyUsedError,
    default_cloud_tasks_name,
)
from proovy_agent.features.video.models import (
    DirectorBriefPolicy,
    SolutionPlan,
    SolutionStep,
    TargetSelection,
    VideoHints,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
)
from proovy_agent.graph.credit_pricing import VIDEO_FLAT_COST
from proovy_agent.graph.nodes import video_node as video_node_module
from proovy_agent.graph.runtime import current_credit_ledger_client, current_video_job_client
from proovy_agent.graph.state import PlanStep, ProovyState


def _solution_plan() -> SolutionPlan:
    return SolutionPlan(
        title="일차방정식",
        steps=[
            SolutionStep(
                step_number=1,
                explanation="양변에 3을 더해 x=5를 얻습니다.",
                latex_expression="x = 5",
            )
        ],
        final_answer="x = 5",
    )


def _video_hints() -> VideoHints:
    return VideoHints(
        visualization_hints=["최종 답 x=5 강조"],
        emphasis_targets=["x = 5"],
        director_policy=DirectorBriefPolicy(brief_template="objects / layout / animation order"),
    )


def _video_input() -> VideoJobInput:
    return VideoJobInput(
        problem_text="x - 3 = 2를 풀어라.",
        solution_plan=_solution_plan(),
        video_hints=_video_hints(),
    )


def _extraction_result() -> HintExtractionResult:
    return HintExtractionResult(
        problem_text="x - 3 = 2를 풀어라.",
        target_selection=TargetSelection(
            target_turn_idx=0,
            problem_text="x - 3 = 2를 풀어라.",
            target_confidence=0.9,
            reasoning="최신 검증 풀이",
        ),
        solution_plan=_solution_plan(),
        video_hints=_video_hints(),
    )


def _job(job_id: str, input_snapshot: VideoJobInput) -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        id=job_id,
        user_id="user-1",
        thread_id="thread-1",
        problem_hash="problem-hash",
        input_snapshot=input_snapshot,
        cloud_tasks_name=default_cloud_tasks_name(job_id),
        status=VideoJobStatus.QUEUED,
        progress_updated_at=now,
        created_at=now,
    )


class _FakeVideoClient:
    def __init__(self, input_snapshot: VideoJobInput | None = None) -> None:
        self.input_snapshot = input_snapshot
        self.create_calls: list[dict[str, object]] = []

    async def create_and_enqueue(
        self,
        *,
        user_id: str,
        thread_id: str,
        input_snapshot: VideoJobInput | None = None,
        retry_source_job_id: str | None = None,
        credit_capture: VideoCreditCapture | None = None,
    ) -> VideoJob:
        self.create_calls.append(
            {
                "user_id": user_id,
                "thread_id": thread_id,
                "input_snapshot": input_snapshot,
                "retry_source_job_id": retry_source_job_id,
                "credit_capture": credit_capture,
            }
        )
        return _job("job-1", input_snapshot or self.input_snapshot or _video_input())


class _FakeLedger:
    def __init__(self) -> None:
        self.release_calls: list[tuple[str, UUID]] = []

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        self.release_calls.append((user_id, hold_id))
        now = datetime.now(UTC)
        return CreditHold(
            id=hold_id,
            user_id=user_id,
            amount=Decimal("0"),
            status=CreditHoldStatus.RELEASED,
            created_at=now,
            expires_at=now + timedelta(minutes=20),
        )


def test_mark_current_step_ignores_negative_index() -> None:
    plan = [
        PlanStep(action="solve", description="풀이", status="done"),
        PlanStep(action="video", description="영상", status="pending"),
    ]

    result = video_node_module._mark_current_step(plan, "done", -1)

    assert [step.status for step in result] == ["done", "pending"]


@pytest.mark.asyncio
async def test_video_node_enqueues_job_captures_credit_and_returns_tool_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold_id = uuid4()
    client = _FakeVideoClient()

    async def fake_extract_video_inputs(messages: object) -> HintExtractionResult:
        assert messages
        return _extraction_result()

    monkeypatch.setattr(video_node_module, "extract_video_inputs", fake_extract_video_inputs)
    token = current_video_job_client.set(client)
    try:
        state = ProovyState(
            user_id="user-1",
            thread_id="thread-1",
            hold_id=str(hold_id),
            messages=[
                HumanMessage(content="x - 3 = 2를 풀어라."),
                AIMessage(
                    content="x=5입니다.",
                    metadata={"kind": "verified_solution", "display": "hidden"},
                ),
            ],
            plan=[
                PlanStep(action="solve", description="풀이", status="done"),
                PlanStep(action="video", description="영상", status="running"),
            ],
            executing_step_idx=1,
        )

        result = await video_node_module.video_node(state)
    finally:
        current_video_job_client.reset(token)

    assert len(client.create_calls) == 1
    call = client.create_calls[0]
    assert call["user_id"] == "user-1"
    assert call["thread_id"] == "thread-1"
    input_snapshot = call["input_snapshot"]
    assert isinstance(input_snapshot, VideoJobInput)
    assert input_snapshot.problem_text == "x - 3 = 2를 풀어라."
    assert input_snapshot.solution_plan == _solution_plan()
    assert input_snapshot.video_hints == _video_hints()
    capture = call["credit_capture"]
    assert isinstance(capture, VideoCreditCapture)
    assert capture.hold_id == hold_id
    assert capture.amount == VIDEO_FLAT_COST

    assert result["plan"][1].status == "done"
    assert result["video_jobs"][0].job_id == "job-1"
    assert result["video_jobs"][0].status == "queued"
    assert result["credit_log"][0].cost == 10.0

    message = result["messages"][0]
    assert "해설 영상을 만들고 있어요" in message.content
    assert message.metadata["display"] == "tool"
    assert message.metadata["tool_name"] == "video_generate"
    assert message.metadata["click_action"] == "open_video_viewer"
    assert message.metadata["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_video_retry_reuses_persisted_input_snapshot_without_extracting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold_id = uuid4()
    client = _FakeVideoClient(input_snapshot=_video_input())

    async def fail_extract_video_inputs(_messages: object) -> HintExtractionResult:
        raise AssertionError("retry should copy the existing job input snapshot")

    monkeypatch.setattr(video_node_module, "extract_video_inputs", fail_extract_video_inputs)
    token = current_video_job_client.set(client)
    try:
        result = await video_node_module.video_node(
            ProovyState(
                user_id="user-1",
                thread_id="thread-1",
                hold_id=str(hold_id),
                messages=[
                    HumanMessage(
                        content="이전 영상 다시 만들기",
                        additional_kwargs={
                            "action": "video_retry",
                            "retry_source_job_id": "failed-job-1",
                        },
                    )
                ],
                plan=[PlanStep(action="video", description="영상", status="running")],
            )
        )
    finally:
        current_video_job_client.reset(token)

    assert client.create_calls[0]["input_snapshot"] is None
    assert client.create_calls[0]["retry_source_job_id"] == "failed-job-1"
    capture = client.create_calls[0]["credit_capture"]
    assert isinstance(capture, VideoCreditCapture)
    assert capture.hold_id == hold_id
    assert capture.amount == VIDEO_FLAT_COST
    assert result["video_jobs"][0].status == "queued"


@pytest.mark.asyncio
async def test_video_node_rejects_without_credit_hold_before_extracting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeVideoClient()

    async def fail_extract_video_inputs(_messages: object) -> HintExtractionResult:
        raise AssertionError("video request without a credit hold must stop before extraction")

    monkeypatch.setattr(video_node_module, "extract_video_inputs", fail_extract_video_inputs)
    token = current_video_job_client.set(client)
    try:
        with pytest.raises(video_node_module.VideoNodePreflightError):
            await video_node_module.video_node(
                ProovyState(
                    user_id="user-1",
                    thread_id="thread-1",
                    messages=[HumanMessage(content="x - 3 = 2 영상 만들어줘")],
                    plan=[PlanStep(action="video", description="영상", status="running")],
                )
            )
    finally:
        current_video_job_client.reset(token)

    assert client.create_calls == []


@pytest.mark.asyncio
async def test_video_retry_defensive_rejection_releases_current_hold() -> None:
    hold_id = uuid4()
    ledger = _FakeLedger()

    class _RejectingVideoClient(_FakeVideoClient):
        async def create_and_enqueue(
            self,
            *,
            user_id: str,
            thread_id: str,
            input_snapshot: VideoJobInput | None = None,
            retry_source_job_id: str | None = None,
            credit_capture: VideoCreditCapture | None = None,
        ) -> VideoJob:
            _ = user_id, thread_id, input_snapshot, retry_source_job_id, credit_capture
            raise RetryAlreadyUsedError("retry already exists")

    video_token = current_video_job_client.set(_RejectingVideoClient())
    credit_token = current_credit_ledger_client.set(ledger)
    try:
        with pytest.raises(video_node_module.VideoNodePreflightError):
            await video_node_module.video_node(
                ProovyState(
                    user_id="user-1",
                    thread_id="thread-1",
                    hold_id=str(hold_id),
                    messages=[
                        HumanMessage(
                            content="이전 영상 다시 만들기",
                            additional_kwargs={
                                "action": "video_retry",
                                "retry_source_job_id": "failed-job-1",
                            },
                        )
                    ],
                    plan=[PlanStep(action="video", description="영상", status="running")],
                )
            )
    finally:
        current_credit_ledger_client.reset(credit_token)
        current_video_job_client.reset(video_token)

    assert ledger.release_calls == [("user-1", hold_id)]


@pytest.mark.asyncio
async def test_video_retry_missing_source_rejects_without_extracting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold_id = uuid4()
    ledger = _FakeLedger()
    client = _FakeVideoClient()

    async def fail_extract_video_inputs(_messages: object) -> HintExtractionResult:
        raise AssertionError("invalid retry should not become a fresh video request")

    monkeypatch.setattr(video_node_module, "extract_video_inputs", fail_extract_video_inputs)
    video_token = current_video_job_client.set(client)
    credit_token = current_credit_ledger_client.set(ledger)
    try:
        with pytest.raises(video_node_module.VideoNodePreflightError):
            await video_node_module.video_node(
                ProovyState(
                    user_id="user-1",
                    thread_id="thread-1",
                    hold_id=str(hold_id),
                    messages=[
                        HumanMessage(
                            content="이전 영상 다시 만들기",
                            additional_kwargs={"action": "video_retry"},
                        )
                    ],
                    plan=[PlanStep(action="video", description="영상", status="running")],
                )
            )
    finally:
        current_credit_ledger_client.reset(credit_token)
        current_video_job_client.reset(video_token)

    assert client.create_calls == []
    assert ledger.release_calls == [("user-1", hold_id)]
