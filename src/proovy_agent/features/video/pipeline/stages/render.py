"""Thin render stage skeleton."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING

from proovy_agent.common.video.timeline import build_segment_timeline
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
            diagnostics={
                "dry_run": True,
                "timeline": _build_timeline_diagnostics(
                    segment_params=segment.params,
                    tts_result=tts_by_segment_id[segment.segment_id],
                    emphasis_targets=(
                        job.input_snapshot.video_hints.emphasis_targets
                        if job.input_snapshot.video_hints is not None
                        else []
                    ),
                ),
            },
        )
        for segment in script.segments
    ]


def _build_timeline_diagnostics(
    *,
    segment_params: Mapping[str, object],
    tts_result: SegmentTTSResult,
    emphasis_targets: list[str],
) -> dict[str, object]:
    timeline = build_segment_timeline(
        total_duration=tts_result.duration_seconds,
        word_timestamps=tts_result.word_timestamps,
        emphasis_targets=emphasis_targets,
        visual_targets=_visual_targets_from_params(segment_params, emphasis_targets),
    )
    return {
        "source": "word_timestamps" if tts_result.word_timestamps else "fallback",
        "total_duration_seconds": timeline.total_duration_seconds,
        "events": [asdict(event) for event in timeline.events],
        "subtitle_cues": [asdict(cue) for cue in timeline.subtitle_cues],
        "unmatched_emphasis_targets": list(timeline.unmatched_emphasis_targets),
        "fallback_reasons": list(timeline.fallback_reasons),
        "used_fallback": timeline.used_fallback,
    }


def _visual_targets_from_params(
    segment_params: Mapping[str, object],
    emphasis_targets: list[str],
) -> dict[str, str]:
    raw_visual_targets = segment_params.get("visual_targets")
    if isinstance(raw_visual_targets, Mapping):
        visual_targets = {
            str(target).strip(): str(target_id).strip()
            for target, target_id in raw_visual_targets.items()
            if str(target).strip() and str(target_id).strip()
        }
        if visual_targets:
            return visual_targets

    return {target.strip(): target.strip() for target in emphasis_targets if target.strip()}
