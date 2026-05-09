"""API v1 router aggregation."""

from fastapi import APIRouter

from proovy_agent.app.api.v1 import health

router = APIRouter()
router.include_router(health.router, tags=["health"])
