"""Shared AsyncDaytona client lifecycle."""

import logging

from daytona import AsyncDaytona, DaytonaConfig

from proovy_agent.common.config import settings

logger = logging.getLogger(__name__)

_client: AsyncDaytona | None = None


async def init_daytona_client() -> None:
    """Initialize the shared AsyncDaytona client once during app startup."""
    global _client
    if _client is not None:
        return
    config = DaytonaConfig(
        api_key=settings.daytona_api_key,
        api_url=settings.daytona_api_url,
        target=settings.daytona_target,
    )
    _client = AsyncDaytona(config)


def get_daytona_client() -> AsyncDaytona:
    """Return the initialized AsyncDaytona client."""
    if _client is None:
        raise RuntimeError("Daytona client not initialized. Call init_daytona_client() first.")
    return _client


async def close_daytona_client() -> None:
    """Close and clear the shared AsyncDaytona client during app shutdown."""
    global _client
    daytona_client = _client
    if daytona_client is None:
        return

    _client = None
    try:
        await daytona_client.close()
    except Exception:
        logger.exception("Failed to close Daytona client")
