"""Pydantic contracts for video generation."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this annotation at runtime.
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FailureKind = Literal["permanent", "transient", "unknown"]


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class _VideoBaseModel(BaseModel):
    """Base config for video data contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class StageName(StrEnum):
    """Pipeline stage names persisted in job status and user diagnostics."""

    SOLVE = "solve"
    SCRIPTIFY = "scriptify"
    TTS = "tts"
    RENDER = "render"
    COMPOSE = "compose"
    ENQUEUE = "enqueue"


class VideoJobStatus(StrEnum):
    """Persisted lifecycle status for an asynchronous video render job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class UserErrorCode(StrEnum):
    """Safe error codes that can be exposed to users."""

    QUEUE_DELAY = "queue_delay"
    LLM_TIMEOUT = "llm_timeout"
    TTS_PROVIDER_DOWN = "tts_provider_down"
    RENDER_RESOURCE_LIMIT = "render_resource_limit"
    RENDER_UNRECOVERABLE = "render_unrecoverable"
    INFRASTRUCTURE_ENQUEUE_FAILED = "infrastructure_enqueue_failed"
    INFRASTRUCTURE_TIMEOUT = "infrastructure_timeout"
    INVALID_INPUT = "invalid_input"
    INVALID_RETRY_SOURCE = "invalid_retry_source"
    RETRY_ALREADY_USED = "retry_already_used"
    UNKNOWN = "unknown"


USER_ERROR_MESSAGES: dict[UserErrorCode, str] = {
    UserErrorCode.QUEUE_DELAY: "영상 작업이 지연되고 있어요. 잠시 후 다시 확인해 주세요.",
    UserErrorCode.LLM_TIMEOUT: "풀이를 영상용 스크립트로 정리하는 데 시간이 오래 걸렸어요. 잠시 후 다시 시도해 주세요.",
    UserErrorCode.TTS_PROVIDER_DOWN: "음성 생성 서비스가 일시적으로 응답하지 않았어요. 잠시 후 다시 시도해 주세요.",
    UserErrorCode.RENDER_RESOURCE_LIMIT: "영상 렌더링에 필요한 리소스가 부족했어요. 잠시 후 다시 시도해 주세요.",
    UserErrorCode.RENDER_UNRECOVERABLE: "영상 일부를 만드는 데 실패했어요. 잠시 후 다시 시도해 주세요.",
    UserErrorCode.INFRASTRUCTURE_ENQUEUE_FAILED: "영상 작업을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.",
    UserErrorCode.INFRASTRUCTURE_TIMEOUT: "영상 작업이 제한 시간을 넘겼어요. 다시 시도해 주세요.",
    UserErrorCode.INVALID_INPUT: "영상 생성에 필요한 풀이 정보를 확인하지 못했어요. 풀이를 다시 요청해 주세요.",
    UserErrorCode.INVALID_RETRY_SOURCE: "이 영상은 다시 시도할 수 없어요.",
    UserErrorCode.RETRY_ALREADY_USED: "이 영상은 다시 만들기를 이미 시도했어요.",
    UserErrorCode.UNKNOWN: "영상 생성 중 알 수 없는 문제가 발생했어요. 잠시 후 다시 시도해 주세요.",
}


def user_error_message(code: UserErrorCode | str) -> str:
    """Return a safe Korean user message for an error code."""
    try:
        error_code = UserErrorCode(code)
    except ValueError:
        error_code = UserErrorCode.UNKNOWN
    return USER_ERROR_MESSAGES[error_code]


class SolutionStep(_VideoBaseModel):
    """Single verified solution step extracted from CoreSolver output."""

    step_number: int = Field(..., ge=1)
    explanation: str
    latex_expression: str | None = None

    @field_validator("explanation")
    @classmethod
    def explanation_not_empty(cls, value: str) -> str:
        return _strip_required(value, "explanation")

    @field_validator("latex_expression")
    @classmethod
    def latex_expression_blank_to_none(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class SolutionPlan(_VideoBaseModel):
    """Structured, verified math solution used by video stages."""

    title: str
    steps: list[SolutionStep]
    final_answer: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, value: str) -> str:
        return _strip_required(value, "title")

    @field_validator("final_answer")
    @classmethod
    def final_answer_blank_to_none(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, value: list[SolutionStep]) -> list[SolutionStep]:
        if not value:
            raise ValueError("steps must contain at least one item")
        return value

    @model_validator(mode="after")
    def validate_step_numbers(self) -> SolutionPlan:
        """Require ordered 1-based step numbers for downstream segment mapping."""
        step_numbers = [step.step_number for step in self.steps]
        expected = list(range(1, len(self.steps) + 1))
        if step_numbers != expected:
            raise ValueError("step_number values must be consecutive starting at 1")
        return self


class TargetSelection(_VideoBaseModel):
    """Stage 1a routing output for resolving the target solve turn."""

    target_turn_idx: int | None = Field(default=None, ge=0)
    problem_text: str
    target_confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str

    @field_validator("problem_text")
    @classmethod
    def problem_text_not_empty(cls, value: str) -> str:
        return _strip_required(value, "problem_text")

    @field_validator("reasoning")
    @classmethod
    def reasoning_not_empty(cls, value: str) -> str:
        return _strip_required(value, "reasoning")


class DirectorBriefPolicy(_VideoBaseModel):
    """Guidance injected into scriptify prompts for visual scene briefs."""

    brief_template: str
    examples: list[str] = Field(default_factory=list)

    @field_validator("brief_template")
    @classmethod
    def brief_template_not_empty(cls, value: str) -> str:
        return _strip_required(value, "brief_template")

    @field_validator("examples")
    @classmethod
    def examples_must_not_be_blank(cls, value: list[str]) -> list[str]:
        stripped = [example.strip() for example in value]
        if any(not example for example in stripped):
            raise ValueError("examples must not contain blank items")
        return stripped


class VideoHints(_VideoBaseModel):
    """Video-owned visualization hints generated after SolutionPlan extraction."""

    visualization_hints: list[str]
    suggested_segments: int | None = Field(default=None, ge=1)
    emphasis_targets: list[str] = Field(default_factory=list)
    director_policy: DirectorBriefPolicy

    @field_validator("visualization_hints")
    @classmethod
    def visualization_hints_not_empty(cls, value: list[str]) -> list[str]:
        stripped = [hint.strip() for hint in value]
        if not stripped:
            raise ValueError("visualization_hints must contain at least one item")
        if any(not hint for hint in stripped):
            raise ValueError("visualization_hints must not contain blank items")
        return stripped

    @field_validator("emphasis_targets")
    @classmethod
    def emphasis_targets_must_not_be_blank(cls, value: list[str]) -> list[str]:
        stripped = [target.strip() for target in value]
        if any(not target for target in stripped):
            raise ValueError("emphasis_targets must not contain blank items")
        return stripped


class VideoOptions(_VideoBaseModel):
    """User and system options for a video generation job."""

    quality: Literal["l", "h"] = "h"
    voice_id: str = "Hyunwoo"
    speaking_rate: float = Field(default=0.95, gt=0)
    diagnostic_dump: bool = False

    @field_validator("voice_id")
    @classmethod
    def voice_id_not_empty(cls, value: str) -> str:
        return _strip_required(value, "voice_id")


class VideoJobInput(_VideoBaseModel):
    """Immutable input snapshot passed from VideoNode to the video worker."""

    problem_text: str
    solution_plan: SolutionPlan | None = None
    video_hints: VideoHints | None = None
    options: VideoOptions = Field(default_factory=VideoOptions)

    @field_validator("problem_text")
    @classmethod
    def problem_text_not_empty(cls, value: str) -> str:
        return _strip_required(value, "problem_text")


class VideoJob(_VideoBaseModel):
    """Persisted async video job record.

    Segment rows and checkpoint/resume fields are intentionally absent for the
    Phase B MVP. Progress is tracked as a compact job-level dict.
    """

    id: str
    user_id: str
    thread_id: str
    problem_hash: str
    input_snapshot: VideoJobInput
    cloud_tasks_name: str
    retry_source_job_id: str | None = None
    status: VideoJobStatus = VideoJobStatus.QUEUED
    stage: StageName | None = None
    progress: dict[str, int] = Field(default_factory=dict)
    lease_holder_instance_id: str | None = None
    progress_updated_at: datetime | None = None
    active_attempt_id: str | None = None
    artifact_object_key: str | None = None
    error_stage: StageName | None = None
    user_error_code: UserErrorCode | None = None
    error_detail: str | None = None
    cost: dict[str, float] = Field(default_factory=dict)
    cancel_requested: bool = False
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @field_validator("id", "user_id", "thread_id", "problem_hash", "cloud_tasks_name")
    @classmethod
    def required_text_not_empty(cls, value: str) -> str:
        return _strip_required(value, "field")

    @field_validator("retry_source_job_id")
    @classmethod
    def retry_source_blank_to_none(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("progress")
    @classmethod
    def progress_values_must_be_non_negative(cls, value: dict[str, int]) -> dict[str, int]:
        if any(progress_value < 0 for progress_value in value.values()):
            raise ValueError("progress values must be non-negative")
        return value

    @field_validator("cost")
    @classmethod
    def cost_values_must_be_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        if any(cost_value < 0 for cost_value in value.values()):
            raise ValueError("cost values must be non-negative")
        return value


class UserDiagnostic(_VideoBaseModel):
    """User-safe diagnostic assembled from job status fields."""

    stage_failed: StageName | None = None
    user_error_code: UserErrorCode = UserErrorCode.UNKNOWN
    retriable: bool = False
    final_video_url: str | None = None
    partial_segments_completed: int | None = Field(default=None, ge=0)

    @field_validator("final_video_url")
    @classmethod
    def final_video_url_blank_to_none(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @model_validator(mode="after")
    def validate_final_url_for_success_only(self) -> UserDiagnostic:
        """Keep successful diagnostics distinct from user-visible failure fields."""
        if not self.final_video_url:
            return self
        if (
            self.stage_failed is not None
            or self.user_error_code is not UserErrorCode.UNKNOWN
            or self.retriable
        ):
            raise ValueError("final_video_url cannot be combined with error fields")
        return self

    @property
    def is_success(self) -> bool:
        """Whether this diagnostic represents a completed video."""
        return self.final_video_url is not None

    @property
    def user_message(self) -> str:
        """Safe localized failure message for client display."""
        if self.is_success:
            return ""
        return user_error_message(self.user_error_code)
