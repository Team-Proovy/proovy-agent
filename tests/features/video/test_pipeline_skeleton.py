"""Video pipeline skeleton tests."""

import asyncio

from pydantic import ValidationError
import pytest

from proovy_agent.features.video.exceptions import (
    InvalidSolutionPlanError,
    InvalidStageOutputError,
    classify_failure,
)
from proovy_agent.features.video.models import (
    FinalVideoArtifact,
    RenderedSegment,
    ScriptSegment,
    SegmentTTSResult,
    SolutionPlan,
    SolutionStep,
    StageName,
    UserErrorCode,
    VideoJobInput,
    VideoPipelineJob,
    VideoPipelineResult,
    VideoScript,
)
from proovy_agent.features.video.pipeline import StageContext, StageEvent, orchestrator, run_job
from proovy_agent.features.video.pipeline.stage_context import StageProgressHandler
from proovy_agent.features.video.pipeline.stages import (
    stage_render,
    stage_scriptify,
    stage_solve,
)
from proovy_agent.features.video.visual_types import VisualTypeRegistry


def _sample_plan() -> SolutionPlan:
    return SolutionPlan(
        title="일차방정식",
        steps=[
            SolutionStep(
                step_number=1,
                explanation="양변에 3을 더합니다.",
                latex_expression="x = 5",
            ),
            SolutionStep(step_number=2, explanation="최종 답을 강조합니다."),
        ],
        final_answer="x = 5",
    )


def _job(solution_plan: SolutionPlan | None = None) -> VideoPipelineJob:
    return VideoPipelineJob(
        job_id="job-1",
        input_snapshot=VideoJobInput(
            problem_text="x - 3 = 2를 풀어라.",
            solution_plan=solution_plan,
        ),
    )


def _raw_job(solution_plan: object) -> VideoPipelineJob:
    return VideoPipelineJob.model_construct(
        job_id="job-1",
        input_snapshot=VideoJobInput.model_construct(
            problem_text="x - 3 = 2를 풀어라.",
            solution_plan=solution_plan,
        ),
    )


def _script() -> VideoScript:
    return VideoScript(
        title="일차방정식",
        segments=[
            ScriptSegment(
                segment_id="step-1",
                order=1,
                visual_type="dry_run",
                narration="양변에 3을 더합니다.",
            ),
            ScriptSegment(
                segment_id="step-2",
                order=2,
                visual_type="dry_run",
                narration="최종 답을 강조합니다.",
            ),
        ],
        final_answer="x = 5",
    )


def test_stage_progress_handler_type_alias_resolves_at_runtime() -> None:
    assert StageProgressHandler.__value__ is not None


async def test_empty_registry_and_stage_context_can_dry_run_pipeline() -> None:
    ctx = StageContext(registry=VisualTypeRegistry())

    result = await run_job(_job(_sample_plan()), ctx=ctx)

    assert result.job_id == "job-1"
    assert result.solution_plan.final_answer == "x = 5"
    assert [segment.segment_id for segment in result.script.segments] == ["step-1", "step-2"]
    assert [segment.visual_type for segment in result.script.segments] == ["dry_run", "dry_run"]
    assert [tts.segment_id for tts in result.tts_results] == ["step-1", "step-2"]
    assert [segment.duration_seconds for segment in result.rendered_segments] == [None, None]
    assert result.final_video.duration_seconds is None
    assert result.final_video.rendered_segment_count == 2


async def test_orchestrator_emits_stable_stage_boundaries() -> None:
    ctx = StageContext()

    await run_job(_job(_sample_plan()), ctx=ctx)

    assert [(event.stage, event.status) for event in ctx.stage_events] == [
        (StageName.SOLVE, "started"),
        (StageName.SOLVE, "completed"),
        (StageName.SCRIPTIFY, "started"),
        (StageName.SCRIPTIFY, "completed"),
        (StageName.TTS, "started"),
        (StageName.TTS, "completed"),
        (StageName.RENDER, "started"),
        (StageName.RENDER, "completed"),
        (StageName.COMPOSE, "started"),
        (StageName.COMPOSE, "completed"),
    ]


async def test_progress_handler_failure_marks_stage_failed() -> None:
    async def fail_on_solve_completed(event: StageEvent) -> None:
        if event.stage is StageName.SOLVE and event.status == "completed":
            raise RuntimeError("progress db write failed")

    ctx = StageContext(progress_handler=fail_on_solve_completed)

    with pytest.raises(RuntimeError, match="progress db write failed"):
        await run_job(_job(_sample_plan()), ctx=ctx)

    assert [(event.stage, event.status) for event in ctx.stage_events] == [
        (StageName.SOLVE, "started"),
        (StageName.SOLVE, "completed"),
        (StageName.SOLVE, "failed"),
    ]


async def test_external_task_cancellation_marks_running_stage_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cancel_tts(*args: object, **kwargs: object) -> list[SegmentTTSResult]:
        raise asyncio.CancelledError

    monkeypatch.setattr(orchestrator, "stage_tts", cancel_tts)
    ctx = StageContext()

    with pytest.raises(asyncio.CancelledError):
        await run_job(_job(_sample_plan()), ctx=ctx)

    assert [(event.stage, event.status) for event in ctx.stage_events] == [
        (StageName.SOLVE, "started"),
        (StageName.SOLVE, "completed"),
        (StageName.SCRIPTIFY, "started"),
        (StageName.SCRIPTIFY, "completed"),
        (StageName.TTS, "started"),
        (StageName.TTS, "failed"),
    ]


async def test_stage_solve_validates_injected_plan_without_re_solve() -> None:
    class ExplodingLLM:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"stage_solve must not access llm.{name}")

    ctx = StageContext(llm=ExplodingLLM())

    plan = await stage_solve(_job(_sample_plan()), ctx=ctx)

    assert plan == _sample_plan()


async def test_missing_solution_plan_fails_at_solve_stage() -> None:
    ctx = StageContext()

    with pytest.raises(InvalidSolutionPlanError, match="solution_plan is required"):
        await run_job(_job(None), ctx=ctx)

    assert [(event.stage, event.status) for event in ctx.stage_events] == [
        (StageName.SOLVE, "started"),
        (StageName.SOLVE, "failed"),
    ]


async def test_invalid_solution_plan_validation_error_maps_to_input_failure() -> None:
    ctx = StageContext()

    with pytest.raises(InvalidSolutionPlanError, match="solution_plan is invalid") as exc_info:
        await run_job(_raw_job({"title": "깨진 풀이", "steps": []}), ctx=ctx)

    assert exc_info.value.user_error_code is UserErrorCode.INVALID_INPUT
    assert classify_failure(exc_info.value) == "permanent"
    assert [(event.stage, event.status) for event in ctx.stage_events] == [
        (StageName.SOLVE, "started"),
        (StageName.SOLVE, "failed"),
    ]


async def test_stage_scriptify_uses_sequential_order_independent_of_source_step_number() -> None:
    raw_plan = SolutionPlan.model_construct(
        title="비연속 원본 단계",
        steps=[
            SolutionStep.model_construct(
                step_number=1,
                explanation="첫 번째 원본 단계",
                latex_expression=None,
            ),
            SolutionStep.model_construct(
                step_number=3,
                explanation="세 번째 원본 단계",
                latex_expression="x = 5",
            ),
        ],
        final_answer="x = 5",
    )

    script = await stage_scriptify(raw_plan, job=_raw_job(raw_plan), ctx=StageContext())

    assert [(segment.segment_id, segment.order) for segment in script.segments] == [
        ("step-1", 1),
        ("step-3", 2),
    ]
    assert [segment.source_step_number for segment in script.segments] == [1, 3]


async def test_stage_render_rejects_missing_or_duplicate_tts_segments() -> None:
    script = _script()
    ctx = StageContext()

    with pytest.raises(InvalidStageOutputError, match="tts_results must match"):
        await stage_render(
            script,
            [SegmentTTSResult(segment_id="step-1", narration="양변에 3을 더합니다.")],
            job=_job(_sample_plan()),
            ctx=ctx,
        )

    with pytest.raises(InvalidStageOutputError, match="tts_results must match"):
        await stage_render(
            script,
            [
                SegmentTTSResult(segment_id="step-1", narration="양변에 3을 더합니다."),
                SegmentTTSResult(segment_id="step-1", narration="중복된 결과입니다."),
            ],
            job=_job(_sample_plan()),
            ctx=ctx,
        )


def test_video_pipeline_result_validates_stage_segment_alignment() -> None:
    script = _script()
    aligned_tts_results = [
        SegmentTTSResult(segment_id="step-1", narration="양변에 3을 더합니다."),
        SegmentTTSResult(segment_id="step-2", narration="최종 답을 강조합니다."),
    ]
    aligned_rendered_segments = [
        RenderedSegment(segment_id="step-1", visual_type="dry_run"),
        RenderedSegment(segment_id="step-2", visual_type="dry_run"),
    ]

    result = VideoPipelineResult(
        job_id="job-1",
        solution_plan=_sample_plan(),
        script=script,
        tts_results=aligned_tts_results,
        rendered_segments=aligned_rendered_segments,
        final_video=FinalVideoArtifact(
            output_path="dry-run.mp4",
            rendered_segment_count=2,
        ),
    )

    assert result.final_video.rendered_segment_count == 2

    with pytest.raises(ValidationError, match="tts_results segment_id values"):
        VideoPipelineResult(
            job_id="job-1",
            solution_plan=_sample_plan(),
            script=script,
            tts_results=[
                SegmentTTSResult(segment_id="step-2", narration="순서가 바뀐 결과입니다."),
                SegmentTTSResult(segment_id="step-1", narration="순서가 바뀐 결과입니다."),
            ],
            rendered_segments=aligned_rendered_segments,
            final_video=FinalVideoArtifact(
                output_path="dry-run.mp4",
                rendered_segment_count=2,
            ),
        )

    with pytest.raises(ValidationError, match="rendered_segment_count"):
        VideoPipelineResult(
            job_id="job-1",
            solution_plan=_sample_plan(),
            script=script,
            tts_results=aligned_tts_results,
            rendered_segments=aligned_rendered_segments,
            final_video=FinalVideoArtifact(
                output_path="dry-run.mp4",
                rendered_segment_count=1,
            ),
        )
