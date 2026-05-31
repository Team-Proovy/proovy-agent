"""Thin render stage skeleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.models import (
    RenderedSegment,
    SegmentTTSResult,
)

if TYPE_CHECKING:
    from proovy_agent.features.video.models import VideoPipelineJob, VideoScript
    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def stage_render(
    script: VideoScript,
    tts_results: list[SegmentTTSResult],
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
) -> list[RenderedSegment]:
    """Return render placeholders and keep unknown duration explicit."""
    _ = (job, ctx)
    tts_by_segment_id = {result.segment_id: result for result in tts_results}
    return [
        RenderedSegment(
            segment_id=segment.segment_id,
            visual_type=segment.visual_type,
            video_path=None,
            duration_seconds=tts_by_segment_id.get(
                segment.segment_id,
                SegmentTTSResult(
                    segment_id=segment.segment_id,
                    narration=segment.narration,
                ),
            ).duration_seconds,
            diagnostics={"dry_run": True},
        )
        for segment in script.segments
    ]
