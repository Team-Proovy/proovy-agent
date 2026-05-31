"""Orchestrator for the staged video generation pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.models import (
    StageName,
    VideoPipelineJob,
    VideoPipelineResult,
)
from proovy_agent.features.video.pipeline.stages import (
    stage_compose,
    stage_render,
    stage_scriptify,
    stage_solve,
    stage_tts,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def _run_stage[StageResult](
    stage: StageName,
    action: Callable[[], Awaitable[StageResult]],
    *,
    ctx: StageContext,
) -> StageResult:
    ctx.raise_if_cancelled()
    await ctx.emit_stage_event(stage, "started")
    try:
        result = await action()
    except Exception:
        await ctx.emit_stage_event(stage, "failed")
        raise
    await ctx.emit_stage_event(stage, "completed")
    return result


async def run_job(job: VideoPipelineJob, *, ctx: StageContext) -> VideoPipelineResult:
    """Run the pipeline from solve validation through compose with no checkpoints."""
    solution_plan = await _run_stage(
        StageName.SOLVE,
        lambda: stage_solve(job, ctx=ctx),
        ctx=ctx,
    )
    script = await _run_stage(
        StageName.SCRIPTIFY,
        lambda: stage_scriptify(solution_plan, job=job, ctx=ctx),
        ctx=ctx,
    )
    tts_results = await _run_stage(
        StageName.TTS,
        lambda: stage_tts(script, job=job, ctx=ctx),
        ctx=ctx,
    )
    rendered_segments = await _run_stage(
        StageName.RENDER,
        lambda: stage_render(script, tts_results, job=job, ctx=ctx),
        ctx=ctx,
    )
    final_video = await _run_stage(
        StageName.COMPOSE,
        lambda: stage_compose(rendered_segments, job=job, ctx=ctx),
        ctx=ctx,
    )
    return VideoPipelineResult(
        job_id=job.job_id,
        solution_plan=solution_plan,
        script=script,
        tts_results=tts_results,
        rendered_segments=rendered_segments,
        final_video=final_video,
    )
