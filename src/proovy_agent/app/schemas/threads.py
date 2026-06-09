"""Thread restoration API schemas."""

from pydantic import BaseModel, Field

from proovy_agent.app.schemas.video_jobs import VideoJobProgressResponse


class ThreadStateResponse(BaseModel):
    """Minimal thread state needed by reconnecting clients."""

    user_id: str
    thread_id: str
    video_jobs: list[VideoJobProgressResponse] = Field(default_factory=list)
