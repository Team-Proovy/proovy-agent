"""Thin TTS stage skeleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.models import SegmentTTSResult

if TYPE_CHECKING:
    from proovy_agent.features.video.models import VideoPipelineJob, VideoScript
    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def stage_tts(
    script: VideoScript,
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
) -> list[SegmentTTSResult]:
    """Return segment-aligned TTS placeholders without provider calls."""
    _ = (job, ctx)
    return [
        SegmentTTSResult(
            segment_id=segment.segment_id,
            narration=segment.narration,
            audio_path=None,
            duration_seconds=None,
            word_timestamps=[],
        )
        for segment in script.segments
    ]
