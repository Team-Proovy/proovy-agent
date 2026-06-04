"""Thin render stage skeleton."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING
import unicodedata

from proovy_agent.common.video.timeline import build_segment_timeline
from proovy_agent.features.video.duration_adjuster import (
    DisallowedNarrationCompressionError,
    adapt_segment_timing,
)
from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.models import (
    RenderedSegment,
    SegmentTTSResult,
    StageName,
    UserErrorCode,
)

if TYPE_CHECKING:
    from proovy_agent.features.video.models import ScriptSegment, VideoPipelineJob, VideoScript
    from proovy_agent.features.video.pipeline.stage_context import StageContext


async def stage_render(
    script: VideoScript,
    tts_results: list[SegmentTTSResult],
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
) -> list[RenderedSegment]:
    """Return render placeholders and keep unknown duration explicit."""
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
    job_emphasis_targets = (
        job.input_snapshot.video_hints.emphasis_targets
        if job.input_snapshot.video_hints is not None
        else []
    )
    allow_job_emphasis_fallback = len(script.segments) == 1
    rendered_segments: list[RenderedSegment] = []
    segment_total = len(script.segments)
    for index, segment in enumerate(script.segments, start=1):
        tts_result = tts_by_segment_id[segment.segment_id]
        try:
            timing_adaptation = adapt_segment_timing(segment=segment, tts_result=tts_result)
        except DisallowedNarrationCompressionError as exc:
            raise InvalidStageOutputError(
                "tts narration changed outside allowed compression policy",
                stage=StageName.RENDER,
                user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
                details={"segment_id": segment.segment_id},
            ) from exc

        diagnostics: dict[str, object] = {
            "dry_run": True,
            "render_mode": "dry_run",
            "tts_first_adaptation": timing_adaptation.to_diagnostics(),
            "timeline": _build_timeline_diagnostics(
                segment_params=segment.params,
                tts_result=tts_result,
                total_duration=timing_adaptation.render_duration_seconds,
                emphasis_targets=_emphasis_targets_from_params(
                    segment.params,
                    job_emphasis_targets=job_emphasis_targets,
                    allow_job_fallback=allow_job_emphasis_fallback,
                ),
            ),
        }
        template_diagnostics = _render_template_diagnostics(segment, ctx=ctx)
        if template_diagnostics is not None:
            diagnostics["render_mode"] = "template_source"
            diagnostics["template"] = template_diagnostics
        rendered_segments.append(
            RenderedSegment(
                segment_id=segment.segment_id,
                visual_type=segment.visual_type,
                video_path=None,
                duration_seconds=timing_adaptation.render_duration_seconds,
                diagnostics=diagnostics,
            )
        )
        await ctx.emit_segment_progress(
            StageName.RENDER,
            segment_id=segment.segment_id,
            segment_index=index,
            segment_total=segment_total,
        )
    return rendered_segments


def _render_template_diagnostics(
    segment: ScriptSegment,
    *,
    ctx: StageContext,
) -> dict[str, object] | None:
    definition = ctx.registry.get(segment.visual_type)
    if definition is None:
        return None
    try:
        ctx.registry.validate_params(segment.visual_type, segment.params)
        output = definition.render_fn(**segment.params)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidStageOutputError(
            "visual_type template render failed",
            stage=StageName.RENDER,
            user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
            details={
                "segment_id": segment.segment_id,
                "visual_type": segment.visual_type,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        ) from exc
    return _template_output_to_diagnostics(output)


def _template_output_to_diagnostics(output: object) -> dict[str, object]:
    as_diagnostics = getattr(output, "as_diagnostics", None)
    if callable(as_diagnostics):
        diagnostics = as_diagnostics()
        if isinstance(diagnostics, Mapping):
            return dict(diagnostics)
    if isinstance(output, Mapping):
        return dict(output)
    return {"kind": type(output).__name__, "repr": repr(output)}


def _build_timeline_diagnostics(
    *,
    segment_params: Mapping[str, object],
    tts_result: SegmentTTSResult,
    total_duration: float | None,
    emphasis_targets: list[str],
) -> dict[str, object]:
    timeline = build_segment_timeline(
        total_duration=total_duration,
        word_timestamps=tts_result.word_timestamps,
        emphasis_targets=emphasis_targets,
        visual_targets=_visual_targets_from_params(segment_params, emphasis_targets),
    )
    return {
        "source": _timeline_source(
            has_word_timestamps=bool(tts_result.word_timestamps),
            has_events=bool(timeline.events),
            used_fallback=timeline.used_fallback,
        ),
        "total_duration_seconds": timeline.total_duration_seconds,
        "events": [asdict(event) for event in timeline.events],
        "subtitle_cues": [asdict(cue) for cue in timeline.subtitle_cues],
        "unmatched_emphasis_targets": list(timeline.unmatched_emphasis_targets),
        "fallback_reasons": list(timeline.fallback_reasons),
        "used_fallback": timeline.used_fallback,
    }


def _emphasis_targets_from_params(
    segment_params: Mapping[str, object],
    *,
    job_emphasis_targets: list[str],
    allow_job_fallback: bool,
) -> list[str]:
    if "emphasis_targets" in segment_params:
        return _string_list_from_param(segment_params.get("emphasis_targets"))
    if allow_job_fallback:
        return _strip_nonempty(job_emphasis_targets)
    return []


def _visual_targets_from_params(
    segment_params: Mapping[str, object],
    emphasis_targets: list[str],
) -> dict[str, str]:
    visual_targets: dict[str, str] = {}
    raw_visual_targets = segment_params.get("visual_targets")
    if isinstance(raw_visual_targets, Mapping):
        visual_targets = {
            str(target).strip(): str(target_id).strip()
            for target, target_id in raw_visual_targets.items()
            if str(target).strip() and str(target_id).strip()
        }

    normalized_visual_target_keys = {
        _normalize_visual_target_key(target) for target in visual_targets
    }
    for target in _strip_nonempty(emphasis_targets):
        normalized_target = _normalize_visual_target_key(target)
        if normalized_target not in normalized_visual_target_keys:
            visual_targets[target] = target
            normalized_visual_target_keys.add(normalized_target)
    return visual_targets


def _timeline_source(
    *,
    has_word_timestamps: bool,
    has_events: bool,
    used_fallback: bool,
) -> str:
    if used_fallback:
        return "fallback"
    if has_events:
        return "emphasis_synced"
    if has_word_timestamps:
        return "word_timestamps"
    return "fallback"


def _string_list_from_param(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return _strip_nonempty([str(item) for item in value])


def _strip_nonempty(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _normalize_visual_target_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("\u2212", "-")
    math_symbols = frozenset("=+-*/^<>")
    return "".join(char for char in normalized if char.isalnum() or char in math_symbols)
