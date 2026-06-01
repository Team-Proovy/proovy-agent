"""Word timestamp based video timeline synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
import unicodedata

if TYPE_CHECKING:
    from proovy_agent.common.tts.models import WordTimestamp

TimelineOp = Literal["play", "wait", "indicate", "fade_in", "fade_out"]

DEFAULT_INDICATE_DURATION_SECONDS = 0.6
MIN_INDICATE_DURATION_SECONDS = 0.2
MAX_TARGET_WINDOW_WORDS = 6

_MATH_SYMBOLS = frozenset("=+-*/^<>")


@dataclass(frozen=True, slots=True)
class AnimEvent:
    """Deterministic visual event at an absolute segment timestamp."""

    at_seconds: float
    op: TimelineOp
    target_id: str | None = None
    duration: float = 0.0
    source_text: str | None = None


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """Word-level subtitle cue aligned to provider timestamps."""

    start_seconds: float
    end_seconds: float
    text: str
    active_word: str


@dataclass(frozen=True, slots=True)
class TimelineSyncResult:
    """Segment timeline with safe fallback diagnostics."""

    total_duration_seconds: float | None
    events: tuple[AnimEvent, ...]
    subtitle_cues: tuple[SubtitleCue, ...]
    unmatched_emphasis_targets: tuple[str, ...]
    fallback_reasons: tuple[str, ...]

    @property
    def used_fallback(self) -> bool:
        """Whether synchronization had to skip or partially skip emphasis."""
        return bool(self.fallback_reasons)


@dataclass(frozen=True, slots=True)
class _WordSpan:
    start_index: int
    end_index: int
    start_seconds: float
    end_seconds: float
    source_text: str


@dataclass(frozen=True, slots=True)
class _EmphasisAlignment:
    events: tuple[AnimEvent, ...]
    unmatched_targets: tuple[str, ...]


def build_timeline_from_word_ts(
    *,
    total_duration: float,
    word_timestamps: list[WordTimestamp],
    emphasis_targets: list[str],
    visual_targets: dict[str, str],
) -> list[AnimEvent]:
    """Build `Indicate` events from word timestamps and emphasis targets."""
    _validate_total_duration(total_duration)
    alignment = _align_emphasis_targets(
        total_duration_seconds=total_duration,
        word_timestamps=word_timestamps,
        emphasis_targets=emphasis_targets,
        visual_targets=visual_targets,
    )
    return list(alignment.events)


def build_segment_timeline(
    *,
    total_duration: float | None,
    word_timestamps: list[WordTimestamp],
    emphasis_targets: list[str],
    visual_targets: dict[str, str],
) -> TimelineSyncResult:
    """Build visual emphasis and subtitle cues from one segment's TTS metadata."""
    resolved_duration = _resolve_total_duration(total_duration, word_timestamps)
    subtitle_cues = tuple(build_word_synced_subtitle_cues(word_timestamps))

    if resolved_duration is None:
        stripped_targets = tuple(_strip_targets(emphasis_targets))
        fallback_reasons = (
            ("missing_word_timestamps",) if stripped_targets and not word_timestamps else ()
        )
        return TimelineSyncResult(
            total_duration_seconds=None,
            events=(),
            subtitle_cues=subtitle_cues,
            unmatched_emphasis_targets=stripped_targets,
            fallback_reasons=fallback_reasons,
        )

    alignment = _align_emphasis_targets(
        total_duration_seconds=resolved_duration,
        word_timestamps=word_timestamps,
        emphasis_targets=emphasis_targets,
        visual_targets=visual_targets,
    )
    fallback_reasons: list[str] = []
    if _strip_targets(emphasis_targets) and not word_timestamps:
        fallback_reasons.append("missing_word_timestamps")
    if alignment.unmatched_targets:
        fallback_reasons.append("unmatched_emphasis_targets")

    return TimelineSyncResult(
        total_duration_seconds=resolved_duration,
        events=alignment.events,
        subtitle_cues=subtitle_cues,
        unmatched_emphasis_targets=alignment.unmatched_targets,
        fallback_reasons=tuple(fallback_reasons),
    )


def build_word_synced_subtitle_cues(
    word_timestamps: list[WordTimestamp],
) -> list[SubtitleCue]:
    """Convert provider word timestamps into word-level subtitle cues."""
    return [
        SubtitleCue(
            start_seconds=timestamp.start,
            end_seconds=timestamp.end,
            text=timestamp.word,
            active_word=timestamp.word,
        )
        for timestamp in word_timestamps
    ]


def frame_index_at(seconds: float, *, frame_rate: float = 30.0) -> int:
    """Return the nearest frame index for a segment-relative timestamp."""
    if seconds < 0:
        raise ValueError("seconds must be greater than or equal to 0")
    if frame_rate <= 0:
        raise ValueError("frame_rate must be greater than 0")
    return round(seconds * frame_rate)


def _align_emphasis_targets(
    *,
    total_duration_seconds: float,
    word_timestamps: list[WordTimestamp],
    emphasis_targets: list[str],
    visual_targets: dict[str, str],
) -> _EmphasisAlignment:
    stripped_targets = tuple(_strip_targets(emphasis_targets))
    if not stripped_targets:
        return _EmphasisAlignment(events=(), unmatched_targets=())

    events: list[AnimEvent] = []
    unmatched_targets: list[str] = []
    for target in stripped_targets:
        target_id = _lookup_visual_target_id(target, visual_targets)
        span = _find_target_span(target, word_timestamps)
        if target_id is None or span is None:
            unmatched_targets.append(target)
            continue

        at_seconds = min(max(span.start_seconds, 0.0), total_duration_seconds)
        duration = _indicate_duration(
            span_start_seconds=at_seconds,
            span_end_seconds=min(max(span.end_seconds, at_seconds), total_duration_seconds),
            total_duration_seconds=total_duration_seconds,
        )
        events.append(
            AnimEvent(
                at_seconds=at_seconds,
                op="indicate",
                target_id=target_id,
                duration=duration,
                source_text=span.source_text,
            )
        )

    events.sort(key=lambda event: (event.at_seconds, event.target_id or ""))
    return _EmphasisAlignment(
        events=tuple(events),
        unmatched_targets=tuple(unmatched_targets),
    )


def _find_target_span(
    target: str,
    word_timestamps: list[WordTimestamp],
) -> _WordSpan | None:
    normalized_target = _normalize_for_match(target)
    if not normalized_target:
        return None

    for start_index in range(len(word_timestamps)):
        normalized_candidate = ""
        source_words: list[str] = []
        last_index = min(start_index + MAX_TARGET_WINDOW_WORDS, len(word_timestamps))
        for end_index in range(start_index, last_index):
            timestamp = word_timestamps[end_index]
            normalized_candidate += _normalize_for_match(timestamp.word)
            source_words.append(timestamp.word)
            if _target_matches_candidate(normalized_target, normalized_candidate):
                return _WordSpan(
                    start_index=start_index,
                    end_index=end_index,
                    start_seconds=word_timestamps[start_index].start,
                    end_seconds=word_timestamps[end_index].end,
                    source_text=" ".join(source_words),
                )
    return None


def _target_matches_candidate(normalized_target: str, normalized_candidate: str) -> bool:
    if not normalized_candidate:
        return False
    if normalized_candidate == normalized_target:
        return True
    if not normalized_candidate.startswith(normalized_target):
        return False
    suffix = normalized_candidate[len(normalized_target) :]
    return bool(suffix) and all(_is_hangul(char) for char in suffix)


def _lookup_visual_target_id(target: str, visual_targets: dict[str, str]) -> str | None:
    target_key = target.strip()
    direct = visual_targets.get(target_key)
    if direct and direct.strip():
        return direct.strip()

    normalized_target = _normalize_for_match(target_key)
    for visual_target, target_id in visual_targets.items():
        if _normalize_for_match(visual_target) == normalized_target and target_id.strip():
            return target_id.strip()
    return None


def _indicate_duration(
    *,
    span_start_seconds: float,
    span_end_seconds: float,
    total_duration_seconds: float,
) -> float:
    remaining_duration = max(0.0, total_duration_seconds - span_start_seconds)
    if remaining_duration == 0:
        return 0.0
    spoken_duration = max(0.0, span_end_seconds - span_start_seconds)
    desired_duration = spoken_duration or DEFAULT_INDICATE_DURATION_SECONDS
    return min(max(desired_duration, MIN_INDICATE_DURATION_SECONDS), remaining_duration)


def _resolve_total_duration(
    total_duration: float | None,
    word_timestamps: list[WordTimestamp],
) -> float | None:
    if total_duration is not None:
        _validate_total_duration(total_duration)
        return total_duration
    if not word_timestamps:
        return None
    return max(timestamp.end for timestamp in word_timestamps)


def _validate_total_duration(total_duration: float) -> None:
    if total_duration < 0:
        raise ValueError("total_duration must be greater than or equal to 0")


def _strip_targets(emphasis_targets: list[str]) -> list[str]:
    return [target.strip() for target in emphasis_targets if target.strip()]


def _normalize_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("\u2212", "-")
    return "".join(char for char in normalized if char.isalnum() or char in _MATH_SYMBOLS)


def _is_hangul(char: str) -> bool:
    return "\uac00" <= char <= "\ud7a3"
