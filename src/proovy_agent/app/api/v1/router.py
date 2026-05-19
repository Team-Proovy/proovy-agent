"""API v1 router aggregation."""

from fastapi import APIRouter

from proovy_agent.app.api.v1 import health, solve

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(solve.router, tags=["solve"])
