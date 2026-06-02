"""Thin compose stage skeleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.models import FinalVideoArtifact

if TYPE_CHECKING:
    from proovy_agent.features.video.models import RenderedSegment, VideoPipelineJob
    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def stage_compose(
    rendered_segments: list[RenderedSegment],
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
) -> FinalVideoArtifact:
    """Return a final artifact contract without ffprobe duration fallback."""
    _ = job
    known_durations = [
        segment.duration_seconds
        for segment in rendered_segments
        if segment.duration_seconds is not None
    ]
    duration_seconds = (
        sum(known_durations) if len(known_durations) == len(rendered_segments) else None
    )
    return FinalVideoArtifact(
        output_path=ctx.dry_run_output_path,
        duration_seconds=duration_seconds,
        rendered_segment_count=len(rendered_segments),
    )
