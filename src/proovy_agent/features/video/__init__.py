"""Video generation domain contracts."""

from proovy_agent.features.video.exceptions import (
    InvalidSolutionPlanError,
    PermanentFailure,
    PipelineError,
    TransientFailure,
    classify_failure,
)
from proovy_agent.features.video.models import (
    DirectorBriefPolicy,
    FailureKind,
    SolutionPlan,
    SolutionStep,
    StageName,
    TargetSelection,
    UserDiagnostic,
    UserErrorCode,
    VideoHints,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
    VideoOptions,
    user_error_message,
)

__all__ = [
    "DirectorBriefPolicy",
    "FailureKind",
    "InvalidSolutionPlanError",
    "PermanentFailure",
    "PipelineError",
    "SolutionPlan",
    "SolutionStep",
    "StageName",
    "TargetSelection",
    "TransientFailure",
    "UserDiagnostic",
    "UserErrorCode",
    "VideoHints",
    "VideoJob",
    "VideoJobInput",
    "VideoJobStatus",
    "VideoOptions",
    "classify_failure",
    "user_error_message",
]
