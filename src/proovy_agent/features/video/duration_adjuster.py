"""TTS-first segment timing adaptation policies."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import re
from typing import TYPE_CHECKING, Literal
import unicodedata

if TYPE_CHECKING:
    from proovy_agent.features.video.models import ScriptSegment, SegmentTTSResult

TimingAdaptationStatus = Literal["converged", "out_of_band", "unknown_duration"]
TimingAdaptationMethod = Literal[
    "none",
    "speed_up_motion",
    "stretch_motion",
    "clamp_to_min_band",
    "hold_final_frame",
    "whitelisted_compression",
    "unknown_duration",
]

MOTION_SPEEDUP_LIMIT = 1.25
MOTION_STRETCH_LIMIT = 1.35
MIN_ALLOWED_COMPRESSION_RETAINED_RATIO = 0.65


@dataclass(frozen=True, slots=True)
class NarrationCompressionRule:
    """One allowed narration-only compression transform."""

    name: str
    source: str
    replacement: str


@dataclass(frozen=True, slots=True)
class NarrationCompressionCheck:
    """Validation result for script narration versus synthesized TTS text."""

    original_narration: str
    tts_narration: str
    compression_applied: bool
    allowed: bool
    applied_rules: tuple[str, ...] = ()
    retained_ratio: float = 1.0

    def to_diagnostics(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic payload."""
        return {
            "compression_applied": self.compression_applied,
            "allowed": self.allowed,
            "applied_rules": list(self.applied_rules),
            "retained_ratio": self.retained_ratio,
        }


@dataclass(frozen=True, slots=True)
class SegmentTimingAdaptation:
    """TTS-first timing decision for one render segment."""

    segment_id: str
    status: TimingAdaptationStatus
    method: TimingAdaptationMethod
    render_duration_seconds: float | None
    tts_duration_seconds: float | None
    base_visual_duration_seconds: float
    min_band_seconds: float
    max_band_seconds: float
    duration_ratio: float | None
    motion_scale: float | None
    compression: NarrationCompressionCheck
    used_resynthesis: bool = False
    fallback_reasons: tuple[str, ...] = ()

    @property
    def converged(self) -> bool:
        """Whether the segment duration falls inside the configured timing band."""
        return self.status == "converged"

    def to_diagnostics(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic payload."""
        return {
            "status": self.status,
            "method": self.method,
            "converged": self.converged,
            "render_duration_seconds": self.render_duration_seconds,
            "tts_duration_seconds": self.tts_duration_seconds,
            "base_visual_duration_seconds": self.base_visual_duration_seconds,
            "min_band_seconds": self.min_band_seconds,
            "max_band_seconds": self.max_band_seconds,
            "duration_ratio": self.duration_ratio,
            "motion_scale": self.motion_scale,
            "compression": self.compression.to_diagnostics(),
            "used_resynthesis": self.used_resynthesis,
            "fallback_reasons": list(self.fallback_reasons),
        }


class DisallowedNarrationCompressionError(ValueError):
    """Raised when TTS narration changed outside the whitelist."""


ALLOWED_NARRATION_COMPRESSION_RULES: tuple[NarrationCompressionRule, ...] = (
    NarrationCompressionRule(
        name="remove_leading_first",
        source="먼저 ",
        replacement="",
    ),
    NarrationCompressionRule(
        name="remove_leading_now",
        source="이제 ",
        replacement="",
    ),
    NarrationCompressionRule(
        name="remove_leading_finally",
        source="마지막으로 ",
        replacement="",
    ),
    NarrationCompressionRule(
        name="shorten_step_by_step_intro",
        source="문제를 단계별로 풀어보겠습니다.",
        replacement="문제를 풀어보겠습니다.",
    ),
    NarrationCompressionRule(
        name="shorten_solution_summary",
        source="풀이 과정을 정리하면 위와 같습니다.",
        replacement="풀이를 정리하면 이렇습니다.",
    ),
    NarrationCompressionRule(
        name="drop_therefore_before_answer",
        source="따라서 정답은",
        replacement="정답은",
    ),
)


def adapt_segment_timing(
    *,
    segment: ScriptSegment,
    tts_result: SegmentTTSResult,
) -> SegmentTimingAdaptation:
    """Adapt render timing to the synthesized TTS duration without resynthesis."""
    compression = validate_narration_compression(
        original_narration=segment.narration,
        tts_narration=tts_result.narration,
    )
    if not compression.allowed:
        raise DisallowedNarrationCompressionError(
            "tts narration changed outside allowed compression policy"
        )

    base_duration = estimate_base_visual_duration(segment)
    min_band_seconds = round(base_duration / MOTION_SPEEDUP_LIMIT, 3)
    max_band_seconds = round(base_duration * MOTION_STRETCH_LIMIT, 3)

    if tts_result.duration_seconds is None:
        return SegmentTimingAdaptation(
            segment_id=segment.segment_id,
            status="unknown_duration",
            method="unknown_duration",
            render_duration_seconds=None,
            tts_duration_seconds=None,
            base_visual_duration_seconds=base_duration,
            min_band_seconds=min_band_seconds,
            max_band_seconds=max_band_seconds,
            duration_ratio=None,
            motion_scale=None,
            compression=compression,
            fallback_reasons=("missing_tts_duration",),
        )

    duration = tts_result.duration_seconds
    duration_ratio = duration / base_duration if base_duration > 0 else 1.0
    motion_scale = _motion_scale(duration_ratio)
    render_duration = duration
    status: TimingAdaptationStatus = "converged"
    fallback_reasons: tuple[str, ...] = ()
    if duration < min_band_seconds:
        status = "out_of_band"
        render_duration = min_band_seconds
        fallback_reasons = ("tts_duration_below_band",)
    elif duration > max_band_seconds:
        status = "out_of_band"
        fallback_reasons = ("tts_duration_above_band",)

    method = _adaptation_method(
        status=status,
        duration_ratio=duration_ratio,
        compression_applied=compression.compression_applied,
    )
    return SegmentTimingAdaptation(
        segment_id=segment.segment_id,
        status=status,
        method=method,
        render_duration_seconds=render_duration,
        tts_duration_seconds=duration,
        base_visual_duration_seconds=base_duration,
        min_band_seconds=min_band_seconds,
        max_band_seconds=max_band_seconds,
        duration_ratio=round(duration_ratio, 3),
        motion_scale=motion_scale,
        compression=compression,
        fallback_reasons=fallback_reasons,
    )


def validate_narration_compression(
    *,
    original_narration: str,
    tts_narration: str,
) -> NarrationCompressionCheck:
    """Validate that TTS text is equal to or whitelisted compression of script text."""
    original = _normalize_narration(original_narration)
    candidate = _normalize_narration(tts_narration)
    if original == candidate:
        return NarrationCompressionCheck(
            original_narration=original,
            tts_narration=candidate,
            compression_applied=False,
            allowed=True,
        )
    if not candidate:
        return NarrationCompressionCheck(
            original_narration=original,
            tts_narration=candidate,
            compression_applied=True,
            allowed=False,
            retained_ratio=0.0,
        )

    retained_ratio = len(candidate) / len(original) if original else 0.0
    variants = _allowed_compression_variants(original)
    applied_rules = variants.get(candidate)
    allowed = applied_rules is not None and retained_ratio >= MIN_ALLOWED_COMPRESSION_RETAINED_RATIO
    return NarrationCompressionCheck(
        original_narration=original,
        tts_narration=candidate,
        compression_applied=True,
        allowed=allowed,
        applied_rules=applied_rules or (),
        retained_ratio=round(retained_ratio, 3),
    )


def estimate_base_visual_duration(segment: ScriptSegment) -> float:
    """Estimate a natural deterministic visual duration before TTS adaptation."""
    params = segment.params
    match segment.visual_type:
        case "intro_problem":
            problem_text = _string_param(params.get("problem_text"))
            return _clamp(2.8 + len(problem_text) / 30.0, minimum=3.0, maximum=6.0)
        case "equation_write":
            return 2.4
        case "equation_derivation":
            latex_steps = params.get("latex_steps")
            step_count = len(latex_steps) if isinstance(latex_steps, list | tuple) else 2
            return _clamp(1.2 + 0.8 * step_count, minimum=2.4, maximum=5.0)
        case "highlight_result":
            return 2.2
        case "outro_summary":
            summary = params.get("summary")
            summary_count = len(summary) if isinstance(summary, list | tuple) else 1
            return _clamp(1.4 + 0.7 * summary_count, minimum=2.1, maximum=5.5)
        case _:
            return 2.5


def _adaptation_method(
    *,
    status: TimingAdaptationStatus,
    duration_ratio: float,
    compression_applied: bool,
) -> TimingAdaptationMethod:
    if status == "out_of_band" and duration_ratio < 1.0 / MOTION_SPEEDUP_LIMIT:
        return "clamp_to_min_band"
    if status == "out_of_band" and duration_ratio > MOTION_STRETCH_LIMIT:
        return "hold_final_frame"
    if compression_applied:
        return "whitelisted_compression"
    if duration_ratio < 0.95:
        return "speed_up_motion"
    if duration_ratio > 1.05:
        return "stretch_motion"
    return "none"


def _allowed_compression_variants(original: str) -> dict[str, tuple[str, ...]]:
    variants: dict[str, tuple[str, ...]] = {}
    rule_indexes = range(len(ALLOWED_NARRATION_COMPRESSION_RULES))
    for size in range(1, len(ALLOWED_NARRATION_COMPRESSION_RULES) + 1):
        for indexes in combinations(rule_indexes, size):
            compressed = original
            applied_names: list[str] = []
            for index in indexes:
                rule = ALLOWED_NARRATION_COMPRESSION_RULES[index]
                next_compressed = _apply_compression_rule(compressed, rule)
                if next_compressed is None:
                    continue
                compressed = next_compressed
                applied_names.append(rule.name)
            if not applied_names:
                continue
            normalized = _normalize_narration(compressed)
            variants.setdefault(normalized, tuple(applied_names))
    return variants


def _normalize_narration(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = re.sub(r"\s+", " ", normalized.strip())
    return re.sub(r"\s+([,.!?\uff0c\u3002])", r"\1", collapsed)


def _apply_compression_rule(
    compressed: str,
    rule: NarrationCompressionRule,
) -> str | None:
    if rule.name.startswith("remove_leading_"):
        if not compressed.startswith(rule.source):
            return None
        return f"{rule.replacement}{compressed.removeprefix(rule.source)}"
    if rule.source not in compressed:
        return None
    return compressed.replace(rule.source, rule.replacement, 1)


def _motion_scale(duration_ratio: float) -> float:
    if duration_ratio < 1.0:
        return round(max(duration_ratio, 1.0 / MOTION_SPEEDUP_LIMIT), 3)
    return round(min(duration_ratio, MOTION_STRETCH_LIMIT), 3)


def _string_param(value: object) -> str:
    return value if isinstance(value, str) else ""


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return round(min(max(value, minimum), maximum), 3)
