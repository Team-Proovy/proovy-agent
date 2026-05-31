"""Thin render stage skeleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.models import (
    RenderedSegment,
    SegmentTTSResult,
    StageName,
    UserErrorCode,
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
    expected_segment_ids = [segment.segment_id for segment in script.segments]
    tts_segment_ids = [result.segment_id for result in tts_results]
    if tts_segment_ids != expected_segment_ids:
        raise InvalidStageOutputError(
            "tts_results must match script segment order",
            stage=StageName.RENDER,
            user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
            details={
                "expected_segment_ids": expected_segment_ids,
                "tts_segment_ids": tts_segment_ids,
            },
        )
    tts_by_segment_id = {result.segment_id: result for result in tts_results}
    return [
        RenderedSegment(
            segment_id=segment.segment_id,
            visual_type=segment.visual_type,
            video_path=None,
            duration_seconds=tts_by_segment_id[segment.segment_id].duration_seconds,
            diagnostics={"dry_run": True},
        )
        for segment in script.segments
    ]
