"""Runtime dependencies visible to graph nodes."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from proovy_agent.features.credits.models import CreditAmount, CreditHold
    from proovy_agent.features.credits.service import CreditLedgerClient
    from proovy_agent.features.video.jobs import VideoJobClient


class ActiveHoldTrackingCreditLedgerClient:
    """Request-scoped ledger wrapper that remembers the currently pending hold."""

    def __init__(self, delegate: CreditLedgerClient) -> None:
        self._delegate = delegate
        self.active_hold_id: UUID | None = None

    async def hold(
        self,
        user_id: str,
        amount: CreditAmount,
        *,
        plan_id: str | None = None,
    ) -> CreditHold:
        hold = await self._delegate.hold(user_id, amount, plan_id=plan_id)
        self.active_hold_id = hold.id
        return hold

    async def finalize_hold(
        self,
        user_id: str,
        hold_id: UUID,
        actual_amount: CreditAmount,
    ) -> CreditHold:
        hold = await self._delegate.finalize_hold(user_id, hold_id, actual_amount)
        if self.active_hold_id == hold_id:
            self.active_hold_id = None
        return hold

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        hold = await self._delegate.release_hold(user_id, hold_id)
        if self.active_hold_id == hold_id:
            self.active_hold_id = None
        return hold

    async def release_active_hold(self, user_id: str) -> CreditHold | None:
        """Release the remembered pending hold, if one exists."""
        if self.active_hold_id is None:
            return None
        hold_id = self.active_hold_id
        return await self.release_hold(user_id, hold_id)


def track_active_credit_hold(
    ledger: CreditLedgerClient | None,
) -> ActiveHoldTrackingCreditLedgerClient | None:
    """Wrap a ledger client so graph runner error paths can release pending holds."""
    if ledger is None:
        return None
    if isinstance(ledger, ActiveHoldTrackingCreditLedgerClient):
        return ledger
    return ActiveHoldTrackingCreditLedgerClient(ledger)


current_credit_ledger_client: ContextVar[CreditLedgerClient | None] = ContextVar(
    "current_credit_ledger_client",
    default=None,
)
current_video_job_client: ContextVar[VideoJobClient | None] = ContextVar(
    "current_video_job_client",
    default=None,
)
