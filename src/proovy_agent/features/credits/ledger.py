"""Atomic operations for the unified credit ledger."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from proovy_agent.common.config import settings
from proovy_agent.features.credits.exceptions import (
    CreditAccountNotFoundError,
    CreditHoldAmountExceededError,
    CreditHoldExpiredError,
    CreditHoldNotFoundError,
    CreditHoldNotPendingError,
    InsufficientCreditsError,
)
from proovy_agent.features.credits.models import (
    CreditAmount,
    CreditBalance,
    CreditHold,
    CreditHoldStatus,
    CreditRefundResult,
    normalize_credit_amount,
)


class CreditLedger:
    """Small repository for atomic balance, hold, capture, and refund operations."""

    def __init__(
        self,
        conn: AsyncConnection[Any],
        *,
        hold_ttl_seconds: int | None = None,
    ) -> None:
        self._conn = conn
        self._hold_ttl_seconds = hold_ttl_seconds or settings.credit_hold_ttl_seconds

    async def upsert_account(self, user_id: str, balance: CreditAmount) -> CreditBalance:
        """Create or overwrite a user's credit account balance."""
        normalized = normalize_credit_amount(balance, allow_zero=True)
        async with self._conn.transaction():
            row = await self._fetchone(
                """
                INSERT INTO credits (user_id, balance, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET balance = EXCLUDED.balance, updated_at = NOW()
                RETURNING user_id, balance
                """,
                (user_id, normalized),
            )
        return CreditBalance(user_id=row["user_id"], balance=row["balance"])

    async def get_balance(self, user_id: str) -> CreditBalance:
        """Return balance minus only pending, unexpired holds."""
        row = await self._fetchone(
            """
            SELECT
                c.user_id,
                c.balance,
                COALESCE(
                    SUM(h.amount) FILTER (
                        WHERE h.status = 'pending' AND h.expires_at > NOW()
                    ),
                    0
                ) AS active_hold_amount
            FROM credits c
            LEFT JOIN credit_holds h ON h.user_id = c.user_id
            WHERE c.user_id = %s
            GROUP BY c.user_id, c.balance
            """,
            (user_id,),
        )
        if row is None:
            raise CreditAccountNotFoundError(user_id)
        return CreditBalance(
            user_id=row["user_id"],
            balance=row["balance"],
            active_hold_amount=row["active_hold_amount"],
        )

    async def hold(
        self,
        user_id: str,
        amount: CreditAmount,
        *,
        plan_id: str | None = None,
        hold_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> CreditHold:
        """Atomically reserve a plan-level hold or reject before any work starts."""
        normalized = normalize_credit_amount(amount)
        hold_id = hold_id or uuid4()

        async with self._conn.transaction():
            account = await self._lock_account(user_id)
            active_held = await self._active_held_amount(user_id)
            available = account["balance"] - active_held
            if available < normalized:
                raise InsufficientCreditsError(
                    user_id=user_id,
                    required=normalized,
                    available=available,
                )

            if expires_at is None:
                row = await self._fetchone(
                    """
                    INSERT INTO credit_holds
                        (id, user_id, amount, status, expires_at, plan_id)
                    VALUES
                        (%s, %s, %s, 'pending',
                         NOW() + (%s * INTERVAL '1 second'), %s)
                    RETURNING id, user_id, amount, status, created_at, expires_at, plan_id
                    """,
                    (hold_id, user_id, normalized, self._hold_ttl_seconds, plan_id),
                )
            else:
                row = await self._fetchone(
                    """
                    INSERT INTO credit_holds
                        (id, user_id, amount, status, expires_at, plan_id)
                    VALUES (%s, %s, %s, 'pending', %s, %s)
                    RETURNING id, user_id, amount, status, created_at, expires_at, plan_id
                    """,
                    (hold_id, user_id, normalized, expires_at, plan_id),
                )

        return _hold_from_row(row)

    async def capture(self, user_id: str, hold_id: UUID, amount: CreditAmount) -> CreditHold:
        """Atomically deduct balance and partially reduce one pending hold row."""
        normalized = normalize_credit_amount(amount)

        async with self._conn.transaction():
            await self._lock_account(user_id)
            hold = await self._lock_hold(user_id, hold_id)
            self._ensure_pending_hold(hold_id, hold)
            if hold["expired"]:
                raise CreditHoldExpiredError(hold_id)
            if hold["amount"] < normalized:
                raise CreditHoldAmountExceededError(
                    hold_id=hold_id,
                    requested=normalized,
                    remaining=hold["amount"],
                )

            await self._conn.execute(
                """
                UPDATE credits
                   SET balance = balance - %s, updated_at = NOW()
                 WHERE user_id = %s
                """,
                (normalized, user_id),
            )
            row = await self._fetchone(
                """
                UPDATE credit_holds
                   SET amount = amount - %s
                 WHERE id = %s AND user_id = %s
                RETURNING id, user_id, amount, status, created_at, expires_at, plan_id
                """,
                (normalized, hold_id, user_id),
            )

        return _hold_from_row(row)

    async def finalize_hold(
        self,
        user_id: str,
        hold_id: UUID,
        actual_amount: CreditAmount,
    ) -> CreditHold:
        """Finalize a pending hold and capture the actual synchronous work cost."""
        normalized = normalize_credit_amount(actual_amount, allow_zero=True)

        async with self._conn.transaction():
            await self._lock_account(user_id)
            hold = await self._lock_hold(user_id, hold_id)
            self._ensure_pending_hold(hold_id, hold)
            if hold["expired"]:
                raise CreditHoldExpiredError(hold_id)

            if normalized > 0:
                await self._conn.execute(
                    """
                    UPDATE credits
                       SET balance = balance - %s, updated_at = NOW()
                     WHERE user_id = %s
                    """,
                    (normalized, user_id),
                )
            row = await self._fetchone(
                """
                UPDATE credit_holds
                   SET status = 'captured'
                 WHERE id = %s AND user_id = %s
                RETURNING id, user_id, amount, status, created_at, expires_at, plan_id
                """,
                (hold_id, user_id),
            )

        return _hold_from_row(row)

    async def release_hold(self, user_id: str, hold_id: UUID) -> CreditHold:
        """Release a pending hold without touching the balance."""
        async with self._conn.transaction():
            await self._lock_account(user_id)
            hold = await self._lock_hold(user_id, hold_id)
            if hold["status"] != CreditHoldStatus.PENDING:
                row = await self._fetchone(
                    """
                    SELECT id, user_id, amount, status, created_at, expires_at, plan_id
                      FROM credit_holds
                     WHERE id = %s AND user_id = %s
                    """,
                    (hold_id, user_id),
                )
            else:
                row = await self._fetchone(
                    """
                    UPDATE credit_holds
                       SET status = 'released'
                     WHERE id = %s AND user_id = %s
                    RETURNING id, user_id, amount, status, created_at, expires_at, plan_id
                    """,
                    (hold_id, user_id),
                )

        return _hold_from_row(row)

    async def refund_if_not_succeeded(
        self,
        job_id: UUID | str,
        amount: CreditAmount,
        *,
        job_table: str = "video_jobs",
    ) -> CreditRefundResult:
        """Apply a video refund once, guarded by the job's current terminal status.

        The referenced job table must expose `id`, `user_id`, `status`, and
        `refund_applied_at` columns. The guarded `UPDATE` is the idempotency key and
        the `status != 'succeeded'` race guard described by ADR 0004.
        """
        normalized = normalize_credit_amount(amount)
        table = sql.Identifier(job_table)

        async with self._conn.transaction():
            refunded = await self._fetchone_composed(
                sql.SQL(
                    """
                    UPDATE {table}
                       SET refund_applied_at = COALESCE(refund_applied_at, NOW())
                     WHERE id = %s
                       AND refund_applied_at IS NULL
                       AND status <> 'succeeded'
                    RETURNING user_id
                    """
                ).format(table=table),
                (job_id,),
            )
            if refunded is None:
                target = await self._fetchone_composed(
                    sql.SQL(
                        """
                        SELECT user_id, status, refund_applied_at
                          FROM {table}
                         WHERE id = %s
                        """
                    ).format(table=table),
                    (job_id,),
                )
                if target is None:
                    return CreditRefundResult(
                        applied=False,
                        skipped_reason="missing_target",
                    )
                reason = "succeeded" if target["status"] == "succeeded" else "already_refunded"
                return CreditRefundResult(
                    applied=False,
                    user_id=target["user_id"],
                    amount=Decimal("0"),
                    skipped_reason=reason,
                )

            credited = await self._fetchone(
                """
                UPDATE credits
                   SET balance = balance + %s, updated_at = NOW()
                 WHERE user_id = %s
                RETURNING user_id
                """,
                (normalized, refunded["user_id"]),
            )
            if credited is None:
                raise CreditAccountNotFoundError(refunded["user_id"])

        return CreditRefundResult(
            applied=True,
            user_id=refunded["user_id"],
            amount=normalized,
        )

    async def _lock_account(self, user_id: str) -> dict[str, Any]:
        row = await self._fetchone(
            """
            SELECT user_id, balance
              FROM credits
             WHERE user_id = %s
             FOR UPDATE
            """,
            (user_id,),
        )
        if row is None:
            raise CreditAccountNotFoundError(user_id)
        return row

    async def _active_held_amount(self, user_id: str) -> Decimal:
        row = await self._fetchone(
            """
            SELECT COALESCE(SUM(amount), 0) AS amount
              FROM credit_holds
             WHERE user_id = %s
               AND status = 'pending'
               AND expires_at > NOW()
            """,
            (user_id,),
        )
        return row["amount"]

    async def _lock_hold(self, user_id: str, hold_id: UUID) -> dict[str, Any]:
        row = await self._fetchone(
            """
            SELECT
                id,
                user_id,
                amount,
                status,
                created_at,
                expires_at,
                plan_id,
                expires_at <= NOW() AS expired
              FROM credit_holds
             WHERE id = %s AND user_id = %s
             FOR UPDATE
            """,
            (hold_id, user_id),
        )
        if row is None:
            raise CreditHoldNotFoundError(hold_id, user_id)
        return row

    @staticmethod
    def _ensure_pending_hold(hold_id: UUID, hold: dict[str, Any]) -> None:
        if hold["status"] != CreditHoldStatus.PENDING:
            raise CreditHoldNotPendingError(hold_id, hold["status"])

    async def _fetchone(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return await cur.fetchone()

    async def _fetchone_composed(
        self,
        query: sql.Composed,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return await cur.fetchone()


def _hold_from_row(row: dict[str, Any]) -> CreditHold:
    return CreditHold(
        id=row["id"],
        user_id=row["user_id"],
        amount=row["amount"],
        status=CreditHoldStatus(row["status"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        plan_id=row["plan_id"],
    )
