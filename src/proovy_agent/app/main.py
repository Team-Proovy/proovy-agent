"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from proovy_agent.app.api.v1.router import router as v1_router
from proovy_agent.common.checkpoint.saver import open_checkpointer
from proovy_agent.common.config import settings
from proovy_agent.common.sandbox.client import close_daytona_client, init_daytona_client
from proovy_agent.features.credits import open_credit_ledger_client
from proovy_agent.features.video.jobs import (
    create_video_artifact_url_resolver,
    create_video_job_client,
)
from proovy_agent.graph.builder import build_graph


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage shared resources for the FastAPI application."""
    await init_daytona_client()
    try:
        async with open_credit_ledger_client(settings) as credit_ledger_client:
            _app.state.credit_ledger_client = credit_ledger_client
            _app.state.video_job_client = create_video_job_client(settings)
            _app.state.video_artifact_url_resolver = create_video_artifact_url_resolver(settings)
            async with open_checkpointer(
                settings.database_url,
                allow_memory_fallback=settings.debug,
            ) as checkpointer:
                build_graph(checkpointer)
                yield
    finally:
        await close_daytona_client()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(v1_router, prefix="/api/v1")

    return app


app = create_app()
