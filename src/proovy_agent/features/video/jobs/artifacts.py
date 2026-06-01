"""Artifact URL resolver contract for video job status responses."""

from typing import Protocol


class VideoArtifactUrlResolver(Protocol):
    """Resolves private artifact object keys to short-lived public URLs."""

    async def final_video_url(self, artifact_object_key: str) -> str | None:
        """Return a signed URL for the final video object, if available."""


class NoopVideoArtifactUrlResolver:
    """Resolver used until the GCS artifact backend is wired."""

    async def final_video_url(self, artifact_object_key: str) -> str | None:
        return None
