"""Word timestamp timeline synchronization tests."""

import pytest

from proovy_agent.common.tts.models import WordTimestamp
from proovy_agent.common.video.timeline import (
    build_segment_timeline,
    build_timeline_from_word_ts,
    build_word_synced_subtitle_cues,
    frame_index_at,
)


def test_timeline_aligns_emphasis_to_provider_word_timestamp_frame() -> None:
    """The visual event starts on the same frame as the matched spoken word."""
    timestamps = [
        WordTimestamp(word="먼저", start=0.0, end=0.3),
        WordTimestamp(word="정답은", start=0.6, end=0.9),
        WordTimestamp(word="x=3입니다.", start=1.2, end=1.7),
    ]

    events = build_timeline_from_word_ts(
        total_duration=2.4,
        word_timestamps=timestamps,
        emphasis_targets=["x=3"],
        visual_targets={"x=3": "answer-mobject"},
    )

    assert len(events) == 1
    event = events[0]
    assert event.op == "indicate"
    assert event.target_id == "answer-mobject"
    assert event.at_seconds == pytest.approx(timestamps[2].start)
    assert frame_index_at(event.at_seconds) == frame_index_at(timestamps[2].start)
    assert event.duration == pytest.approx(0.5)
    assert event.source_text == "x=3입니다."


def test_timeline_matches_split_korean_emphasis_target() -> None:
    """A target like 빨간색 can match adjacent WORD tokens split by the provider."""
    timestamps = [
        WordTimestamp(word="빨간", start=0.4, end=0.7),
        WordTimestamp(word="색", start=0.7, end=0.9),
    ]

    timeline = build_segment_timeline(
        total_duration=1.5,
        word_timestamps=timestamps,
        emphasis_targets=["빨간색"],
        visual_targets={"빨간색": "red-region"},
    )

    assert timeline.used_fallback is False
    assert timeline.unmatched_emphasis_targets == ()
    assert [event.at_seconds for event in timeline.events] == [pytest.approx(0.4)]
    assert timeline.events[0].duration == pytest.approx(0.5)
    assert timeline.events[0].source_text == "빨간 색"


def test_word_synced_subtitles_consume_provider_word_timestamps() -> None:
    """Subtitle cues preserve the TTS word timestamp contract without guessing duration."""
    timestamps = [
        WordTimestamp(word="양변에", start=0.0, end=0.35),
        WordTimestamp(word="3을", start=0.35, end=0.62),
    ]

    cues = build_word_synced_subtitle_cues(timestamps)

    assert [(cue.start_seconds, cue.end_seconds, cue.active_word) for cue in cues] == [
        (0.0, 0.35, "양변에"),
        (0.35, 0.62, "3을"),
    ]


def test_timeline_fallback_keeps_video_segment_renderable_when_target_is_unmatched() -> None:
    """Unmatched emphasis is reported as fallback diagnostics instead of raising."""
    timeline = build_segment_timeline(
        total_duration=2.0,
        word_timestamps=[WordTimestamp(word="다른", start=0.0, end=0.3)],
        emphasis_targets=["x=3"],
        visual_targets={"x=3": "answer"},
    )

    assert timeline.events == ()
    assert timeline.unmatched_emphasis_targets == ("x=3",)
    assert timeline.fallback_reasons == ("unmatched_emphasis_targets",)
    assert timeline.used_fallback is True


def test_timeline_fallback_reports_missing_word_timestamps_without_guessing() -> None:
    """Missing timestamps leave timing empty and mark a bounded fallback."""
    timeline = build_segment_timeline(
        total_duration=None,
        word_timestamps=[],
        emphasis_targets=["교점"],
        visual_targets={"교점": "intersection"},
    )

    assert timeline.total_duration_seconds is None
    assert timeline.events == ()
    assert timeline.subtitle_cues == ()
    assert timeline.unmatched_emphasis_targets == ("교점",)
    assert timeline.fallback_reasons == ("missing_word_timestamps",)
