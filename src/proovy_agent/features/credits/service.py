"""Runtime client for graph credit ledger operations."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from proovy_agent.common.checkpoint.saver import _to_libpq
from proovy_agent.common.config import settings
from proovy_agent.features.credits.ledger import CreditLedger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from proovy_agent.common.config import Settings
    from proovy_agent.features.credits.models import CreditAmount, CreditHold


class CreditLedgerClient(Protocol):
    """Graph-facing credit ledger operations."""

    async def hold(
        self,
        user_id: str,
        amount: CreditAmount,
        *,
        plan_id: str | None = None,
    ) -> CreditHold:
        """Reserve a plan-level hold."""

    async def finalize_hold(
        self,
        user_id: str,
        hold_id: UUID,
        actual_amount: CreditAmount,
    ) -> CreditHold:
        """Capture synchronous work cost and release the remaining hold."""

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        """Release a pending hold without touching balance."""


class PostgresCreditLedgerClient:
    """Postgres-backed graph credit ledger client."""

    def __init__(
        self,
        database_url: str,
        *,
        hold_ttl_seconds: int | None = None,
        pool: AsyncConnectionPool | None = None,
    ) -> None:
        self._database_url = _to_libpq(database_url)
        self._hold_ttl_seconds = hold_ttl_seconds
        self._pool = pool

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        if self._pool is not None:
            async with self._pool.connection() as conn:
                yield conn
            return

        async with await AsyncConnection.connect(self._database_url) as conn:
            yield conn

    async def hold(
        self,
        user_id: str,
        amount: CreditAmount,
        *,
        plan_id: str | None = None,
    ) -> CreditHold:
        async with self._connection() as conn:
            return await CreditLedger(
                conn,
                hold_ttl_seconds=self._hold_ttl_seconds,
            ).hold(user_id, amount, plan_id=plan_id)

    async def finalize_hold(
        self,
        user_id: str,
        hold_id: UUID,
        actual_amount: CreditAmount,
    ) -> CreditHold:
        async with self._connection() as conn:
            return await CreditLedger(
                conn,
                hold_ttl_seconds=self._hold_ttl_seconds,
            ).finalize_hold(user_id, hold_id, actual_amount)

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        async with self._connection() as conn:
            return await CreditLedger(
                conn,
                hold_ttl_seconds=self._hold_ttl_seconds,
            ).release_hold(user_id, hold_id)


def create_credit_ledger_client(
    app_settings: Settings = settings,
) -> CreditLedgerClient | None:
    """Create the default credit ledger client for graph nodes."""
    if not app_settings.database_url:
        return None
    return PostgresCreditLedgerClient(
        app_settings.database_url,
        hold_ttl_seconds=app_settings.credit_hold_ttl_seconds,
    )


@asynccontextmanager
async def open_credit_ledger_client(
    app_settings: Settings = settings,
) -> AsyncIterator[CreditLedgerClient | None]:
    """Open the app-scoped pooled credit ledger client."""
    if not app_settings.database_url:
        yield None
        return

    pool = AsyncConnectionPool(_to_libpq(app_settings.database_url), open=False)
    await pool.open()
    try:
        yield PostgresCreditLedgerClient(
            app_settings.database_url,
            hold_ttl_seconds=app_settings.credit_hold_ttl_seconds,
            pool=pool,
        )
    finally:
        await pool.close()
