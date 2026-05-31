"""Thin scriptify stage skeleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.models import (
    ScriptSegment,
    VideoScript,
)

if TYPE_CHECKING:
    from proovy_agent.features.video.models import SolutionPlan, VideoPipelineJob
    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def stage_scriptify(
    plan: SolutionPlan,
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
) -> VideoScript:
    """Produce deterministic placeholder segments from the verified plan."""
    _ = job
    segments = [
        ScriptSegment(
            segment_id=f"step-{step.step_number}",
            order=step.step_number,
            visual_type=ctx.default_visual_type,
            narration=step.explanation,
            params={"latex_expression": step.latex_expression}
            if step.latex_expression is not None
            else {},
            source_step_number=step.step_number,
        )
        for step in plan.steps
    ]
    return VideoScript(
        title=plan.title,
        segments=segments,
        final_answer=plan.final_answer,
    )
