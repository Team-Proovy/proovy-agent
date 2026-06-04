"""Video worker runner tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from proovy_agent.features.video.jobs import InMemoryVideoJobRepository
from proovy_agent.features.video.models import (
    FinalVideoArtifact,
    RenderedSegment,
    ScriptSegment,
    SegmentTTSResult,
    SolutionPlan,
    SolutionStep,
    StageName,
    VideoJobInput,
    VideoJobStatus,
    VideoPipelineJob,
    VideoPipelineResult,
    VideoScript,
)
from proovy_agent.features.video.worker import VideoWorkerRunner, VideoWorkerRunStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from proovy_agent.features.video.pipeline import StageContext


class _RecordingRepository(InMemoryVideoJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.progress_writes: list[tuple[StageName | None, dict[str, int]]] = []

    async def update_progress(
        self,
        job_id: str,
        *,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ):
        self.progress_writes.append((stage, dict(progress or {})))
        return await super().update_progress(
            job_id,
            stage=stage,
            progress=progress,
            status=status,
        )


def _sample_plan() -> SolutionPlan:
    return SolutionPlan(
        title="일차방정식",
        steps=[
            SolutionStep(
                step_number=1,
                explanation="양변에서 1을 뺍니다.",
                latex_expression="2x = 6",
            ),
            SolutionStep(
                step_number=2,
                explanation="양변을 2로 나눕니다.",
                latex_expression="x = 3",
            ),
        ],
        final_answer="x = 3",
    )


def _sample_input() -> VideoJobInput:
    return VideoJobInput(
        problem_text="2x + 1 = 7을 풀어라.",
        solution_plan=_sample_plan(),
    )


def _empty_result(job: VideoPipelineJob) -> VideoPipelineResult:
    script = VideoScript(
        title="일차방정식",
        segments=[
            ScriptSegment(
                segment_id="segment-1",
                order=1,
                visual_type="dry_run",
                narration="풀이를 정리합니다.",
            )
        ],
        final_answer="x = 3",
    )
    return VideoPipelineResult(
        job_id=job.job_id,
        solution_plan=_sample_plan(),
        script=script,
        tts_results=[SegmentTTSResult(segment_id="segment-1", narration="풀이를 정리합니다.")],
        rendered_segments=[RenderedSegment(segment_id="segment-1", visual_type="dry_run")],
        final_video=FinalVideoArtifact(output_path="final.mp4", rendered_segment_count=1),
    )


async def test_worker_runner_runs_job_and_records_stage_and_segment_progress() -> None:
    """잡 1건이 worker runner에서 stage를 순회하고 progress를 기록한다."""
    repository = _RecordingRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=0.01,
        cancel_poll_interval_seconds=0.01,
        job_max_runtime_seconds=5,
    )

    result = await runner.run(job.id)

    loaded = await repository.get(job.id)
    assert loaded is not None
    assert result.status is VideoWorkerRunStatus.COMPLETED
    assert loaded.status is VideoJobStatus.SUCCEEDED
    assert loaded.stage is StageName.COMPOSE
    assert loaded.progress == {
        "stages_completed": 5,
        "stages_total": 5,
        "stage_index": 5,
    }
    assert loaded.artifact_object_key is not None
    assert f"video-jobs/{job.id}/attempts/" in loaded.artifact_object_key
    assert any(
        stage is StageName.SOLVE and progress["stages_completed"] == 0
        for stage, progress in repository.progress_writes
    )
    assert any(
        stage is StageName.TTS and progress.get("segments_done", 0) > 0
        for stage, progress in repository.progress_writes
    )
    assert any(
        stage is StageName.RENDER and progress.get("segments_done", 0) > 0
        for stage, progress in repository.progress_writes
    )


async def test_repository_lease_expiry_takeover_and_self_fence() -> None:
    """lease 만료 후 다른 worker가 탈취하고 이전 holder heartbeat는 self-fence된다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    first = await repository.acquire_lease(
        job.id,
        instance_id="worker-a",
        attempt_id="attempt-a",
        lease_stale_after_seconds=60,
    )
    blocked = await repository.acquire_lease(
        job.id,
        instance_id="worker-b",
        attempt_id="attempt-b",
        lease_stale_after_seconds=60,
    )
    stolen = await repository.acquire_lease(
        job.id,
        instance_id="worker-b",
        attempt_id="attempt-b",
        lease_stale_after_seconds=0,
    )
    stale_heartbeat = await repository.heartbeat_lease(job.id, instance_id="worker-a")

    assert first is not None
    assert first.lease_holder_instance_id == "worker-a"
    assert first.active_attempt_id == "attempt-a"
    assert blocked is None
    assert stolen is not None
    assert stolen.lease_holder_instance_id == "worker-b"
    assert stolen.active_attempt_id == "attempt-b"
    assert stale_heartbeat is None


async def test_runner_self_fences_when_lease_is_stolen() -> None:
    """worker heartbeat가 lease 탈취를 감지하면 terminal write 없이 중단한다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    stage_started = asyncio.Event()

    async def slow_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.SOLVE, "started")
        stage_started.set()
        await asyncio.Event().wait()
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-a",
        heartbeat_interval_seconds=0.01,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=slow_pipeline,
    )
    run_task = asyncio.create_task(runner.run(job.id))
    await asyncio.wait_for(stage_started.wait(), timeout=1)
    stolen = await repository.acquire_lease(
        job.id,
        instance_id="worker-b",
        attempt_id="attempt-b",
        lease_stale_after_seconds=0,
    )

    result = await asyncio.wait_for(run_task, timeout=1)
    loaded = await repository.get(job.id)

    assert stolen is not None
    assert result.status is VideoWorkerRunStatus.SELF_FENCED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.RUNNING
    assert loaded.lease_holder_instance_id == "worker-b"


async def test_cancel_poll_marks_running_job_canceled() -> None:
    """10초 cancel poll 경로가 cancel_requested를 감지하면 canceled terminal로 남긴다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    stage_started = asyncio.Event()

    async def slow_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.RENDER, "started")
        stage_started.set()
        await asyncio.Event().wait()
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=0.01,
        job_max_runtime_seconds=5,
        pipeline_runner=slow_pipeline,
    )
    run_task = asyncio.create_task(runner.run(job.id))
    await asyncio.wait_for(stage_started.wait(), timeout=1)
    await repository.request_cancel(job.id)

    result = await asyncio.wait_for(run_task, timeout=1)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.CANCELED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.CANCELED
    assert loaded.cancel_requested is True
    assert loaded.lease_holder_instance_id is None


async def test_stage_boundary_cancel_is_checked_before_next_stage() -> None:
    """stage 경계에서 cancel_requested를 재조회하고 다음 stage를 시작하지 않는다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    async def boundary_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.SOLVE, "started")
        await repository.request_cancel(job.job_id)
        await ctx.emit_stage_event(StageName.SOLVE, "completed")
        ctx.raise_if_cancelled()
        await ctx.emit_stage_event(StageName.SCRIPTIFY, "started")
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=boundary_pipeline,
    )

    result = await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.CANCELED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.CANCELED
    assert loaded.stage is StageName.SOLVE
