"""Thin TTS stage skeleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proovy_agent.features.video.models import SegmentTTSResult, StageName

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
    _ = job
    results: list[SegmentTTSResult] = []
    segment_total = len(script.segments)
    for index, segment in enumerate(script.segments, start=1):
        results.append(
            SegmentTTSResult(
                segment_id=segment.segment_id,
                narration=segment.narration,
                audio_path=None,
                duration_seconds=None,
                word_timestamps=[],
            )
        )
        await ctx.emit_segment_progress(
            StageName.TTS,
            segment_id=segment.segment_id,
            segment_index=index,
            segment_total=segment_total,
        )
    return results
