"""Video pipeline skeleton tests."""

import pytest

from proovy_agent.features.video.exceptions import InvalidSolutionPlanError
from proovy_agent.features.video.models import (
    SolutionPlan,
    SolutionStep,
    StageName,
    VideoJobInput,
    VideoPipelineJob,
)
from proovy_agent.features.video.pipeline import StageContext, run_job
from proovy_agent.features.video.pipeline.stages import stage_solve
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
