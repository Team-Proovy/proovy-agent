"""Health check endpoint."""

from fastapi import APIRouter

from proovy_agent.common.config import settings

router = APIRouter()


@router.get("/health", summary="헬스체크")
def health_check() -> dict[str, str]:
    """Return service health information."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }
