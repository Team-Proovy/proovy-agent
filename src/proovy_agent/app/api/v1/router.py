"""API v1 router aggregation."""

from fastapi import APIRouter

from proovy_agent.app.api.v1 import health, solve, threads, video_jobs

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(solve.router, tags=["solve"])
router.include_router(threads.router, tags=["threads"])
router.include_router(video_jobs.router, tags=["video_jobs"])
