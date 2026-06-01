"""Runtime dependencies visible to graph nodes."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proovy_agent.features.credits.service import CreditLedgerClient
    from proovy_agent.features.video.jobs import VideoJobClient


current_credit_ledger_client: ContextVar[CreditLedgerClient | None] = ContextVar(
    "current_credit_ledger_client",
    default=None,
)
current_video_job_client: ContextVar[VideoJobClient | None] = ContextVar(
    "current_video_job_client",
    default=None,
)
