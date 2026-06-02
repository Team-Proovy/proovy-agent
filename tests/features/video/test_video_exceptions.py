"""Video pipeline exception tests."""

from proovy_agent.features.video.exceptions import (
    InvalidSolutionPlanError,
    PermanentFailure,
    PipelineError,
    TransientFailure,
    classify_failure,
)
from proovy_agent.features.video.models import StageName, UserErrorCode


def test_pipeline_error_builds_safe_user_diagnostic_without_raw_details() -> None:
    """Raw exception text and details stay out of user diagnostics."""
    error = PermanentFailure(
        "stderr: Traceback with /var/tmp/secret.py",
        stage=StageName.RENDER,
        user_error_code=UserErrorCode.RENDER_UNRECOVERABLE,
        details={"stderr": "Traceback with API_KEY=secret"},
    )

    diagnostic = error.to_user_diagnostic(partial_segments_completed=1)
    dumped = diagnostic.model_dump(mode="json")

    assert dumped == {
        "stage_failed": "render",
        "user_error_code": "render_unrecoverable",
        "retriable": False,
        "final_video_url": None,
        "partial_segments_completed": 1,
    }
    assert "Traceback" not in diagnostic.user_message
    assert "API_KEY" not in diagnostic.user_message
    assert error.safe_message == diagnostic.user_message


def test_invalid_solution_plan_error_has_input_contract_code() -> None:
    """Missing or invalid injected SolutionPlan is a permanent input contract failure."""
    error = InvalidSolutionPlanError("solution_plan is missing")

    assert error.stage is StageName.SOLVE
    assert error.user_error_code is UserErrorCode.INVALID_INPUT
    assert classify_failure(error) == "permanent"


def test_transient_failures_are_retryable() -> None:
    """TransientFailure and runtime transient types classify for Cloud Tasks retry."""
    error = TransientFailure(
        "OpenRouter timeout",
        stage=StageName.SCRIPTIFY,
        user_error_code=UserErrorCode.LLM_TIMEOUT,
    )

    assert error.retryable is True
    assert error.to_user_diagnostic().retriable is True
    assert classify_failure(error) == "transient"
    assert classify_failure(TimeoutError()) == "transient"
    assert classify_failure(MemoryError()) == "transient"
    assert classify_failure(ConnectionError()) == "transient"


def test_unknown_failures_remain_unclassified_for_worker_policy() -> None:
    """Unmapped exceptions stay unknown so the worker can apply conservative policy."""
    assert classify_failure(PipelineError("base error")) == "unknown"
    assert classify_failure(RuntimeError("unexpected")) == "unknown"
