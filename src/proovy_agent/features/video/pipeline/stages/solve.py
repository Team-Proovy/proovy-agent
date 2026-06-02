"""Solve stage for validating injected CoreSolver output."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from proovy_agent.features.video.exceptions import InvalidSolutionPlanError
from proovy_agent.features.video.models import SolutionPlan

if TYPE_CHECKING:
    from proovy_agent.features.video.models import VideoPipelineJob
    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def stage_solve(job: VideoPipelineJob, *, ctx: StageContext) -> SolutionPlan:
    """Validate the injected SolutionPlan without re-solving the problem."""
    _ = ctx
    solution_plan = job.input_snapshot.solution_plan
    if solution_plan is None:
        raise InvalidSolutionPlanError("solution_plan is required for video pipeline")
    try:
        return SolutionPlan.model_validate(solution_plan)
    except ValidationError as exc:
        raise InvalidSolutionPlanError("solution_plan is invalid") from exc
