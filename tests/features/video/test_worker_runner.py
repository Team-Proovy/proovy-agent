"""Video worker runner tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING

from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.jobs import InMemoryVideoJobRepository
from proovy_agent.features.video.models import (
    FinalVideoArtifact,
    RenderedSegment,
    ScriptSegment,
    SegmentTTSResult,
    SolutionPlan,
    SolutionStep,
    StageName,
    UserErrorCode,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
    VideoPipelineJob,
    VideoPipelineResult,
    VideoScript,
)
from proovy_agent.features.video.worker import VideoWorkerRunner, VideoWorkerRunStatus
from proovy_agent.features.video.worker.sandbox import RenderSandboxResourceLimitError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from proovy_agent.features.video.pipeline import StageContext


class _RecordingRepository(InMemoryVideoJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.progress_writes: list[tuple[StageName | None, dict[str, int]]] = []

    async def update_progress_for_lease(
        self,
        job_id: str,
        *,
        instance_id: str,
        stage: StageName | None = None,
        progress: Mapping[str, int] | None = None,
        status: VideoJobStatus | None = None,
    ):
        self.progress_writes.append((stage, dict(progress or {})))
        return await super().update_progress_for_lease(
            job_id,
            instance_id=instance_id,
            stage=stage,
            progress=progress,
            status=status,
        )


class _HeartbeatFailsRepository(InMemoryVideoJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.heartbeat_calls = 0

    async def heartbeat_lease(self, job_id: str, *, instance_id: str) -> VideoJob | None:
        self.heartbeat_calls += 1
        return None


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


async def test_worker_runner_injects_render_sandbox_into_stage_context() -> None:
    """worker render는 생성 코드를 직접 실행하지 않고 StageContext sandbox 경계를 쓴다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    render_sandbox = object()

    async def sandbox_asserting_pipeline(
        job: VideoPipelineJob,
        *,
        ctx: StageContext,
    ) -> VideoPipelineResult:
        assert ctx.sandbox is render_sandbox
        await ctx.emit_stage_event(StageName.RENDER, "started")
        await ctx.emit_stage_event(StageName.RENDER, "completed")
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=sandbox_asserting_pipeline,
        render_sandbox=render_sandbox,
    )

    result = await runner.run(job.id)

    assert result.status is VideoWorkerRunStatus.COMPLETED


async def test_worker_runner_marks_render_sandbox_resource_limit_as_failed_job() -> None:
    """resource limit 위반은 Cloud Tasks retry가 아니라 render 실패로 terminal 처리한다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    async def failing_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.RENDER, "started")
        raise RenderSandboxResourceLimitError("render sub-process exceeded timeout")

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=failing_pipeline,
    )

    result = await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.FAILED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.FAILED
    assert loaded.error_stage is StageName.RENDER
    assert loaded.user_error_code is UserErrorCode.RENDER_RESOURCE_LIMIT


async def test_worker_runner_persists_latex_validation_diagnostics_on_failure() -> None:
    """LaTeX audit 실패 원인은 내부 error_detail에 안전 JSON으로 남긴다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    latex_error = {
        "message": "LaTeX command \\input is not allowed in render templates.",
        "line": 3,
        "column": 12,
        "error_code": "latex_file_read",
        "severity": "error",
        "original_snippet": r"MathTex(r'\input{/etc/passwd}')",
    }

    async def failing_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.RENDER, "started")
        raise InvalidStageOutputError(
            "visual_type template failed LaTeX safety validation",
            stage=StageName.RENDER,
            user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
            details={"latex_validation_errors": [latex_error]},
        )

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=failing_pipeline,
    )

    result = await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.FAILED
    assert loaded is not None
    assert loaded.error_detail is not None
    detail = json.loads(loaded.error_detail)
    assert detail == {
        "error_type": "InvalidStageOutputError",
        "diagnostics": {"template": {"latex_validation_errors": [latex_error]}},
    }


async def test_worker_runner_keeps_large_latex_diagnostics_as_valid_bounded_json() -> None:
    """큰 LaTeX audit 결과도 잘린 JSON 문자열이 되지 않는다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    latex_errors = [
        {
            "message": "unsafe latex command " + ("x" * 1000),
            "line": index + 1,
            "column": 1,
            "error_code": "latex_file_read",
            "severity": "error",
            "original_snippet": "x" * 1000,
        }
        for index in range(20)
    ]

    async def failing_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.RENDER, "started")
        raise InvalidStageOutputError(
            "visual_type template failed LaTeX safety validation",
            stage=StageName.RENDER,
            user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
            details={"latex_validation_errors": latex_errors},
        )

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=failing_pipeline,
    )

    await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert loaded is not None
    assert loaded.error_detail is not None
    assert len(loaded.error_detail) <= 8000
    detail = json.loads(loaded.error_detail)
    errors = detail["diagnostics"]["template"]["latex_validation_errors"]
    assert 0 < len(errors) < len(latex_errors)
    assert errors[0]["message"].startswith("unsafe latex command")


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


async def test_request_cancel_does_not_refresh_lease_liveness() -> None:
    """cancel signal은 lease heartbeat가 아니므로 stale takeover 시간을 연장하지 않는다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    leased = await repository.acquire_lease(
        job.id,
        instance_id="worker-a",
        attempt_id="attempt-a",
        lease_stale_after_seconds=60,
    )
    assert leased is not None

    stale_timestamp = datetime.now(UTC) - timedelta(seconds=120)
    repository._jobs[job.id] = repository._jobs[job.id].model_copy(
        update={"progress_updated_at": stale_timestamp}
    )

    canceled = await repository.request_cancel(job.id)
    stolen = await repository.acquire_lease(
        job.id,
        instance_id="worker-b",
        attempt_id="attempt-b",
        lease_stale_after_seconds=60,
    )

    assert canceled.cancel_requested is True
    assert canceled.progress_updated_at == stale_timestamp
    assert stolen is not None
    assert stolen.lease_holder_instance_id == "worker-b"
    assert stolen.cancel_requested is True


async def test_worker_runner_marks_live_foreign_lease_as_busy_skip() -> None:
    """MVP에서는 live foreign lease 중복 delivery를 ack하되 outcome을 분리한다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    await repository.acquire_lease(
        job.id,
        instance_id="worker-a",
        attempt_id="attempt-a",
        lease_stale_after_seconds=60,
    )
    runner = VideoWorkerRunner(repository, instance_id="worker-b")

    result = await runner.run(job.id)

    assert result.status is VideoWorkerRunStatus.SKIPPED_BUSY
    assert result.job_status is VideoJobStatus.RUNNING


async def test_worker_progress_write_requires_current_lease_holder() -> None:
    """lease를 잃은 worker의 in-flight progress write는 새 holder 상태를 덮지 않는다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )
    await repository.acquire_lease(
        job.id,
        instance_id="worker-a",
        attempt_id="attempt-a",
        lease_stale_after_seconds=60,
    )
    stolen = await repository.acquire_lease(
        job.id,
        instance_id="worker-b",
        attempt_id="attempt-b",
        lease_stale_after_seconds=0,
    )

    stale_update = await repository.update_progress_for_lease(
        job.id,
        instance_id="worker-a",
        status=VideoJobStatus.RUNNING,
        stage=StageName.RENDER,
        progress={"segments_done": 99, "segments_total": 99},
    )
    loaded = await repository.get(job.id)

    assert stolen is not None
    assert stale_update is None
    assert loaded is not None
    assert loaded.lease_holder_instance_id == "worker-b"
    assert loaded.stage is None
    assert loaded.progress == {}


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


async def test_runner_does_not_finalize_success_after_lease_is_stolen() -> None:
    """성공 직후에도 lease를 잃었으면 stale worker가 artifact를 terminal로 쓰지 않는다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    async def stealing_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.SOLVE, "started")
        stolen = await repository.acquire_lease(
            job.job_id,
            instance_id="worker-b",
            attempt_id="attempt-b",
            lease_stale_after_seconds=0,
        )
        assert stolen is not None
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-a",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=stealing_pipeline,
    )

    result = await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.SELF_FENCED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.RUNNING
    assert loaded.lease_holder_instance_id == "worker-b"
    assert loaded.artifact_object_key is None


async def test_runner_success_finalize_is_guarded_without_post_pipeline_heartbeat() -> None:
    """성공 terminal write는 별도 heartbeat gate가 아니라 lease-guarded finalize로 확정한다."""
    repository = _HeartbeatFailsRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    async def quick_pipeline(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.SOLVE, "started")
        await ctx.emit_stage_event(StageName.SOLVE, "completed")
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-a",
        heartbeat_interval_seconds=60,
        cancel_poll_interval_seconds=60,
        job_max_runtime_seconds=5,
        pipeline_runner=quick_pipeline,
    )

    result = await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.COMPLETED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.SUCCEEDED
    assert loaded.lease_holder_instance_id is None
    assert repository.heartbeat_calls == 0


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


async def test_final_stage_completed_cancel_is_checked_before_success() -> None:
    """최종 stage 완료 직후 cancel_requested가 보이면 succeeded로 finalize하지 않는다."""
    repository = InMemoryVideoJobRepository()
    job = await repository.create(
        user_id="user-1",
        thread_id="thread-1",
        input_snapshot=_sample_input(),
    )

    async def final_stage_pipeline(
        job: VideoPipelineJob, *, ctx: StageContext
    ) -> VideoPipelineResult:
        await ctx.emit_stage_event(StageName.COMPOSE, "started")
        await repository.request_cancel(job.job_id)
        await ctx.emit_stage_event(StageName.COMPOSE, "completed")
        return _empty_result(job)

    runner = VideoWorkerRunner(
        repository,
        instance_id="worker-1",
        heartbeat_interval_seconds=1,
        cancel_poll_interval_seconds=1,
        job_max_runtime_seconds=5,
        pipeline_runner=final_stage_pipeline,
    )

    result = await runner.run(job.id)
    loaded = await repository.get(job.id)

    assert result.status is VideoWorkerRunStatus.CANCELED
    assert loaded is not None
    assert loaded.status is VideoJobStatus.CANCELED
    assert loaded.artifact_object_key is None
