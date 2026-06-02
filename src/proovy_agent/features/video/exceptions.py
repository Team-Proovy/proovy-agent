"""Exception hierarchy for video generation pipeline failures.

Provider and infrastructure errors should be wrapped as PermanentFailure or
TransientFailure near their stage boundary. Unknown failures are kept explicit
so the worker can apply its conservative terminal-failure policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from proovy_agent.features.video.models import (
    FailureKind,
    StageName,
    UserDiagnostic,
    UserErrorCode,
    user_error_message,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class PipelineError(Exception):
    """Base exception for video pipeline failures."""

    user_error_code: UserErrorCode = UserErrorCode.UNKNOWN
    stage: StageName | None = None
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        stage: StageName | str | None = None,
        user_error_code: UserErrorCode | str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = StageName(stage) if stage is not None else self.stage
        if user_error_code is not None:
            self.user_error_code = UserErrorCode(user_error_code)
        self.details = dict(details or {})

    @property
    def safe_message(self) -> str:
        """User-safe localized message that never includes raw exception details."""
        return user_error_message(self.user_error_code)

    def to_user_diagnostic(
        self,
        *,
        final_video_url: str | None = None,
        partial_segments_completed: int | None = None,
    ) -> UserDiagnostic:
        """Build a user-safe diagnostic payload from this exception policy."""
        return UserDiagnostic(
            stage_failed=self.stage,
            user_error_code=self.user_error_code,
            retriable=self.retryable,
            final_video_url=final_video_url,
            partial_segments_completed=partial_segments_completed,
        )


class PermanentFailure(PipelineError):  # noqa: N818 - design uses Failure taxonomy names.
    """Failure that should be marked failed and refunded without Cloud Tasks retry."""

    retryable = False


class TransientFailure(PipelineError):  # noqa: N818 - design uses Failure taxonomy names.
    """Failure that should release lease and let Cloud Tasks retry."""

    retryable = True


class InvalidSolutionPlanError(PermanentFailure):
    """Video worker received an invalid or missing SolutionPlan."""

    user_error_code = UserErrorCode.INVALID_INPUT
    stage = StageName.SOLVE


class InvalidStageOutputError(PermanentFailure):
    """A pipeline stage produced output that violates the next stage contract.

    The failing stage should be passed at the raise site because this error is
    shared by multiple stage boundaries.
    """

    user_error_code = UserErrorCode.UNKNOWN


_PERMANENT_TYPES = (PermanentFailure,)
_TRANSIENT_TYPES = (TransientFailure, TimeoutError, MemoryError, ConnectionError)


def classify_failure(exc: Exception) -> FailureKind:
    """Classify a failure for worker retry/refund behavior."""
    if isinstance(exc, _PERMANENT_TYPES):
        return "permanent"
    if isinstance(exc, _TRANSIENT_TYPES):
        return "transient"
    return "unknown"
