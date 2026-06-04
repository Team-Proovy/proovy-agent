"""TTS-first duration adaptation policy tests."""

import pytest

from proovy_agent.features.video.duration_adjuster import (
    DisallowedNarrationCompressionError,
    adapt_segment_timing,
    validate_narration_compression,
)
from proovy_agent.features.video.models import ScriptSegment, SegmentTTSResult


def _equation_segment(narration: str = "양변에 3을 더합니다.") -> ScriptSegment:
    return ScriptSegment(
        segment_id="step-1",
        order=1,
        visual_type="equation_write",
        narration=narration,
        params={
            "latex_expression": "x = 5",
            "visual_description": "핵심 식을 한 줄로 표시합니다.",
        },
    )


def test_tts_duration_inside_band_converges_by_micro_motion_adjustment() -> None:
    segment = _equation_segment()
    tts_result = SegmentTTSResult(
        segment_id="step-1",
        narration="양변에 3을 더합니다.",
        duration_seconds=3.0,
    )

    adaptation = adapt_segment_timing(segment=segment, tts_result=tts_result)

    assert adaptation.status == "converged"
    assert adaptation.method == "stretch_motion"
    assert adaptation.render_duration_seconds == 3.0
    assert adaptation.min_band_seconds == pytest.approx(1.92)
    assert adaptation.max_band_seconds == pytest.approx(3.24)
    assert adaptation.motion_scale == pytest.approx(1.25)
    assert adaptation.used_resynthesis is False


def test_tts_narration_may_only_use_whitelisted_compression_rules() -> None:
    original = "먼저 일차방정식 문제를 단계별로 풀어보겠습니다."
    candidate = "일차방정식 문제를 풀어보겠습니다."

    check = validate_narration_compression(
        original_narration=original,
        tts_narration=candidate,
    )

    assert check.allowed is True
    assert check.compression_applied is True
    assert check.applied_rules == (
        "remove_leading_first",
        "shorten_step_by_step_intro",
    )
    assert check.retained_ratio >= 0.65


def test_disallowed_narration_change_is_rejected() -> None:
    segment = _equation_segment()
    tts_result = SegmentTTSResult(
        segment_id="step-1",
        narration="정답은 x=5입니다.",
        duration_seconds=2.4,
    )

    with pytest.raises(DisallowedNarrationCompressionError):
        adapt_segment_timing(segment=segment, tts_result=tts_result)


def test_tts_duration_below_band_clamps_render_duration_to_min_band() -> None:
    segment = _equation_segment()
    tts_result = SegmentTTSResult(
        segment_id="step-1",
        narration="양변에 3을 더합니다.",
        duration_seconds=1.0,
    )

    adaptation = adapt_segment_timing(segment=segment, tts_result=tts_result)

    assert adaptation.status == "out_of_band"
    assert adaptation.method == "clamp_to_min_band"
    assert adaptation.render_duration_seconds == pytest.approx(adaptation.min_band_seconds)
    assert adaptation.tts_duration_seconds == 1.0
    assert adaptation.motion_scale == pytest.approx(0.8)
    assert adaptation.used_resynthesis is False
    assert adaptation.fallback_reasons == ("tts_duration_below_band",)


def test_out_of_band_duration_is_marked_without_resynthesis() -> None:
    segment = _equation_segment()
    tts_result = SegmentTTSResult(
        segment_id="step-1",
        narration="양변에 3을 더합니다.",
        duration_seconds=6.0,
    )

    adaptation = adapt_segment_timing(segment=segment, tts_result=tts_result)

    assert adaptation.status == "out_of_band"
    assert adaptation.method == "hold_final_frame"
    assert adaptation.render_duration_seconds == 6.0
    assert adaptation.used_resynthesis is False
    assert adaptation.fallback_reasons == ("tts_duration_above_band",)


def test_leading_compression_rule_does_not_remove_middle_occurrences() -> None:
    original = "먼저 설명하고, 먼저 양변에 더합니다."

    leading_only = validate_narration_compression(
        original_narration=original,
        tts_narration="설명하고, 먼저 양변에 더합니다.",
    )
    over_compressed = validate_narration_compression(
        original_narration=original,
        tts_narration="설명하고, 양변에 더합니다.",
    )

    assert leading_only.allowed is True
    assert leading_only.applied_rules == ("remove_leading_first",)
    assert over_compressed.allowed is False


def test_narration_compression_normalizes_unicode_compatibility_forms() -> None:
    check = validate_narration_compression(
        original_narration="정답은 x\uff1d\uff13입니다.",
        tts_narration="정답은 x=3입니다.",
    )

    assert check.allowed is True
    assert check.compression_applied is False


def test_missing_tts_duration_keeps_unknown_duration_explicit() -> None:
    segment = _equation_segment()
    tts_result = SegmentTTSResult(
        segment_id="step-1",
        narration="양변에 3을 더합니다.",
    )

    adaptation = adapt_segment_timing(segment=segment, tts_result=tts_result)

    assert adaptation.status == "unknown_duration"
    assert adaptation.method == "unknown_duration"
    assert adaptation.render_duration_seconds is None
    assert adaptation.fallback_reasons == ("missing_tts_duration",)
