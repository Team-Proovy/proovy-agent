"""Video contract model tests."""

from pydantic import ValidationError
import pytest

from proovy_agent.features.video.models import (
    DirectorBriefPolicy,
    SolutionPlan,
    SolutionStep,
    StageName,
    TargetSelection,
    UserDiagnostic,
    UserErrorCode,
    VideoHints,
    VideoJobInput,
    VideoOptions,
    user_error_message,
)


def _sample_solution_plan() -> SolutionPlan:
    return SolutionPlan(
        title="일차방정식 풀이",
        steps=[
            SolutionStep(
                step_number=1,
                explanation="양변에서 2를 뺍니다.",
                latex_expression="x = 3",
            )
        ],
        final_answer="x = 3",
    )


def _sample_video_hints() -> VideoHints:
    return VideoHints(
        visualization_hints=["좌변과 우변을 나란히 배치", "최종 답 x=3 강조"],
        suggested_segments=6,
        emphasis_targets=["x=3"],
        director_policy=DirectorBriefPolicy(
            brief_template="objects / layout / animation order",
            examples=["Good: show both sides before simplifying"],
        ),
    )


def test_video_job_input_round_trips_json_contract() -> None:
    """VideoJobInput serializes and validates back from a JSON-mode snapshot."""
    original = VideoJobInput(
        problem_text="2x + 1 = 7을 풀어라.",
        solution_plan=_sample_solution_plan(),
        video_hints=_sample_video_hints(),
        options=VideoOptions(quality="l", voice_id="Hyunwoo", speaking_rate=0.9),
    )

    dumped = original.model_dump(mode="json")
    restored = VideoJobInput.model_validate(dumped)

    assert restored == original
    assert dumped["options"] == {
        "quality": "l",
        "voice_id": "Hyunwoo",
        "speaking_rate": 0.9,
        "diagnostic_dump": False,
    }
    assert "visualization_hints" not in dumped["solution_plan"]
    assert dumped["video_hints"]["visualization_hints"] == [
        "좌변과 우변을 나란히 배치",
        "최종 답 x=3 강조",
    ]


def test_solution_plan_rejects_empty_steps_and_blank_text() -> None:
    """SolutionPlan requires a title and at least one verified step."""
    with pytest.raises(ValidationError, match="steps must contain at least one item"):
        SolutionPlan(title="풀이", steps=[])

    with pytest.raises(ValidationError, match="explanation must not be empty"):
        SolutionStep(step_number=1, explanation="  ")


def test_solution_plan_rejects_non_consecutive_step_numbers() -> None:
    """SolutionPlan requires ordered 1-based step numbers."""
    with pytest.raises(ValidationError, match="consecutive starting at 1"):
        SolutionPlan(
            title="풀이",
            steps=[
                SolutionStep(step_number=1, explanation="첫 단계"),
                SolutionStep(step_number=1, explanation="중복 단계"),
            ],
        )

    with pytest.raises(ValidationError, match="consecutive starting at 1"):
        SolutionPlan(
            title="풀이",
            steps=[
                SolutionStep(step_number=2, explanation="시작 번호가 잘못된 단계"),
            ],
        )


def test_video_hints_reject_blank_visualization_hints() -> None:
    """VideoHints owns visualization hints and requires meaningful values."""
    with pytest.raises(ValidationError, match="visualization_hints must not contain blank items"):
        VideoHints(
            visualization_hints=["좌표평면 표시", " "],
            director_policy=DirectorBriefPolicy(
                brief_template="objects / layout / animation order"
            ),
        )


def test_target_selection_contract_validates_routing_fields() -> None:
    """Stage 1a target selection has bounded confidence and optional turn index."""
    selection = TargetSelection(
        target_turn_idx=2,
        problem_text="아까 푼 이차방정식",
        target_confidence=0.72,
        reasoning="사용자가 '아까 1번'을 참조했다.",
    )

    assert selection.model_dump(mode="json") == {
        "target_turn_idx": 2,
        "problem_text": "아까 푼 이차방정식",
        "target_confidence": 0.72,
        "reasoning": "사용자가 '아까 1번'을 참조했다.",
    }

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        TargetSelection(
            problem_text="문제",
            target_confidence=1.5,
            reasoning="confidence 범위 초과",
        )


def test_user_diagnostic_serializes_only_safe_error_fields() -> None:
    """User diagnostics expose stage and safe code, not raw stderr/details."""
    diagnostic = UserDiagnostic(
        stage_failed=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
        retriable=True,
        partial_segments_completed=3,
    )

    assert diagnostic.model_dump(mode="json") == {
        "stage_failed": "render",
        "user_error_code": "render_unrecoverable",
        "retriable": True,
        "final_video_url": None,
        "partial_segments_completed": 3,
    }
    assert diagnostic.user_message == user_error_message(UserErrorCode.RENDER_UNRECOVERABLE)


def test_user_diagnostic_success_has_no_failure_message() -> None:
    """Successful diagnostics expose a URL without an error display message."""
    diagnostic = UserDiagnostic(final_video_url="https://storage.example/video.mp4")

    assert diagnostic.is_success is True
    assert diagnostic.user_message == ""

    with pytest.raises(ValidationError, match="cannot be combined with error fields"):
        UserDiagnostic(
            final_video_url="https://storage.example/video.mp4",
            stage_failed=StageName.RENDER,
        )

    with pytest.raises(ValidationError, match="cannot be combined with error fields"):
        UserDiagnostic(
            final_video_url="https://storage.example/video.mp4",
            user_error_code=UserErrorCode.UNKNOWN,
            retriable=True,
        )

    with pytest.raises(ValidationError, match="cannot be combined with error fields"):
        UserDiagnostic(
            final_video_url="https://storage.example/video.mp4",
            user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
        )


def test_all_user_error_codes_have_messages() -> None:
    """Every safe user error code maps to a localized display message."""
    for code in UserErrorCode:
        assert user_error_message(code)

    assert user_error_message("not_a_real_code") == user_error_message(UserErrorCode.UNKNOWN)
