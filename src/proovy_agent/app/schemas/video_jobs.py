"""Video job API schemas."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from proovy_agent.features.video.models import (
    StageName,
    UserDiagnostic,
    VideoJob,
    VideoJobInput,
    VideoJobStatus,
)


class CreateVideoJobRequest(BaseModel):
    """Request body for creating a new async video job."""

    user_id: str = Field(..., description="사용자 ID")
    thread_id: str = Field(..., description="대화 쓰레드 ID")
    input_snapshot: VideoJobInput | None = Field(
        default=None,
        description="새 영상 잡 입력 스냅샷",
        validation_alias=AliasChoices("input_snapshot", "input"),
    )
    retry_source_job_id: str | None = Field(
        default=None,
        description="사용자 재시도 원본 잡 ID",
    )

    @field_validator("user_id")
    @classmethod
    def _no_colon_in_user_id(cls, value: str) -> str:
        if ":" in value:
            raise ValueError("user_id must not contain ':'")
        return value

    @model_validator(mode="after")
    def validate_new_or_retry(self) -> "CreateVideoJobRequest":
        if self.retry_source_job_id and self.input_snapshot is not None:
            raise ValueError("retry request must not include a new input_snapshot")
        if not self.retry_source_job_id and self.input_snapshot is None:
            raise ValueError("input_snapshot is required for new video jobs")
        return self


class CreateVideoJobResponse(BaseModel):
    """Response returned immediately after a job is accepted."""

    job_id: str
    status: VideoJobStatus
    progress_url: str
    poll_after_seconds: int = Field(default=2, ge=1)


class VideoJobProgressResponse(BaseModel):
    """Hot-path progress response for one video job."""

    job_id: str
    status: VideoJobStatus
    stage: StageName | None
    progress: dict[str, int]
    progress_updated_at: datetime | None
    poll_after_seconds: int = Field(default=2, ge=1)
    retry_source_job_id: str | None
    can_user_retry: bool
    artifact_object_key: str | None
    user_diagnostic: UserDiagnostic | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_job(
        cls,
        job: VideoJob,
        *,
        can_user_retry: bool,
        user_diagnostic: UserDiagnostic | None,
    ) -> "VideoJobProgressResponse":
        return cls(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            progress_updated_at=job.progress_updated_at,
            retry_source_job_id=job.retry_source_job_id,
            can_user_retry=can_user_retry,
            artifact_object_key=job.artifact_object_key,
            user_diagnostic=user_diagnostic,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
