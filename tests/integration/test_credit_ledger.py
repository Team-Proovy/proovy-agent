"""Postgres-backed unified credit ledger integration tests.

DATABASE_URL 미설정 시 skip — docker-compose.test.yml의 postgres 서비스로 실행한다:

    docker compose -f docker-compose.test.yml run --rm test-pg
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from uuid import UUID, uuid4

import psycopg
from psycopg import AsyncConnection, sql
import pytest

from proovy_agent.features.credits import (
    CreditHoldStatus,
    CreditLedger,
    InsufficientCreditsError,
    setup_credit_ledger,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL 미설정 — Postgres 통합 테스트 건너뜀")
    return url


@asynccontextmanager
async def _connect(database_url: str) -> AsyncIterator[AsyncConnection]:
    conn = await psycopg.AsyncConnection.connect(database_url)
    try:
        yield conn
    finally:
        await conn.close()


async def _create_job_table(conn: AsyncConnection, table_name: str) -> None:
    await conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name)))
    await conn.execute(
        sql.SQL(
            """
            CREATE TABLE {} (
                id UUID PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                refund_applied_at TIMESTAMPTZ
            )
            """
        ).format(sql.Identifier(table_name))
    )
    await conn.commit()


async def _insert_job(
    conn: AsyncConnection,
    table_name: str,
    *,
    job_id: UUID,
    user_id: str,
    status: str,
) -> None:
    await conn.execute(
        sql.SQL("INSERT INTO {} (id, user_id, status) VALUES (%s, %s, %s)").format(
            sql.Identifier(table_name)
        ),
        (job_id, user_id, status),
    )
    await conn.commit()


async def _job_refund_applied(conn: AsyncConnection, table_name: str, job_id: UUID) -> bool:
    row = await conn.execute(
        sql.SQL("SELECT refund_applied_at IS NOT NULL FROM {} WHERE id = %s").format(
            sql.Identifier(table_name)
        ),
        (job_id,),
    )
    value = await row.fetchone()
    assert value is not None
    return bool(value[0])


async def test_hold_capture_finalize_uses_single_hold_row(database_url: str) -> None:
    user_id = f"credit-user-{uuid4()}"

    async with _connect(database_url) as conn:
        await setup_credit_ledger(conn)
        ledger = CreditLedger(conn)
        await ledger.upsert_account(user_id, "20")

        hold = await ledger.hold(user_id, "15", plan_id="plan-1")
        assert hold.status is CreditHoldStatus.PENDING

        captured = await ledger.capture(user_id, hold.id, "10")
        assert captured.id == hold.id
        assert captured.amount == Decimal("5")
        assert captured.status is CreditHoldStatus.PENDING

        balance_after_video = await ledger.get_balance(user_id)
        assert balance_after_video.balance == Decimal("10")
        assert balance_after_video.active_hold_amount == Decimal("5")
        assert balance_after_video.available == Decimal("5")

        finalized = await ledger.finalize_hold(user_id, hold.id, "3")
        assert finalized.id == hold.id
        assert finalized.status is CreditHoldStatus.CAPTURED
        assert finalized.amount == Decimal("5")

        final_balance = await ledger.get_balance(user_id)
        assert final_balance.balance == Decimal("7")
        assert final_balance.active_hold_amount == Decimal("0")
        assert final_balance.available == Decimal("7")


async def test_concurrent_holds_are_all_or_nothing(database_url: str) -> None:
    user_id = f"credit-concurrent-{uuid4()}"

    async with _connect(database_url) as setup_conn:
        await setup_credit_ledger(setup_conn)
        await CreditLedger(setup_conn).upsert_account(user_id, "10")

    async def reserve(plan_id: str) -> object:
        async with _connect(database_url) as conn:
            return await CreditLedger(conn).hold(user_id, "7", plan_id=plan_id)

    results = await asyncio.gather(
        reserve("plan-a"),
        reserve("plan-b"),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, InsufficientCreditsError)]
    assert len(successes) == 1
    assert len(failures) == 1

    async with _connect(database_url) as verify_conn:
        balance = await CreditLedger(verify_conn).get_balance(user_id)
        assert balance.balance == Decimal("10")
        assert balance.active_hold_amount == Decimal("7")
        assert balance.available == Decimal("3")


async def test_expired_pending_holds_recover_on_read_without_sweep(database_url: str) -> None:
    user_id = f"credit-ttl-{uuid4()}"
    expired_at = datetime.now(UTC) - timedelta(seconds=1)

    async with _connect(database_url) as conn:
        await setup_credit_ledger(conn)
        ledger = CreditLedger(conn)
        await ledger.upsert_account(user_id, "10")

        expired_hold = await ledger.hold(
            user_id,
            "8",
            plan_id="orphan-plan",
            expires_at=expired_at,
        )
        assert expired_hold.status is CreditHoldStatus.PENDING

        balance = await ledger.get_balance(user_id)
        assert balance.balance == Decimal("10")
        assert balance.active_hold_amount == Decimal("0")
        assert balance.available == Decimal("10")

        fresh_hold = await ledger.hold(user_id, "10", plan_id="new-plan")
        assert fresh_hold.amount == Decimal("10")

        row = await conn.execute(
            "SELECT status FROM credit_holds WHERE id = %s",
            (expired_hold.id,),
        )
        expired_status = await row.fetchone()
        assert expired_status == ("pending",)


async def test_refund_is_idempotent(database_url: str) -> None:
    user_id = f"credit-refund-{uuid4()}"
    job_id = uuid4()
    job_table = f"credit_test_jobs_{uuid4().hex}"

    async with _connect(database_url) as conn:
        await setup_credit_ledger(conn)
        await _create_job_table(conn, job_table)
        ledger = CreditLedger(conn)
        await ledger.upsert_account(user_id, "10")
        await _insert_job(conn, job_table, job_id=job_id, user_id=user_id, status="failed")

        first = await ledger.refund_if_not_succeeded(job_id, "10", job_table=job_table)
        second = await ledger.refund_if_not_succeeded(job_id, "10", job_table=job_table)

        assert first.applied is True
        assert first.amount == Decimal("10")
        assert second.applied is False
        assert second.skipped_reason == "already_refunded"
        assert await _job_refund_applied(conn, job_table, job_id) is True

        balance = await ledger.get_balance(user_id)
        assert balance.balance == Decimal("20")


async def test_refund_skips_succeeded_job(database_url: str) -> None:
    user_id = f"credit-succeeded-{uuid4()}"
    job_id = uuid4()
    job_table = f"credit_test_jobs_{uuid4().hex}"

    async with _connect(database_url) as conn:
        await setup_credit_ledger(conn)
        await _create_job_table(conn, job_table)
        ledger = CreditLedger(conn)
        await ledger.upsert_account(user_id, "10")
        await _insert_job(conn, job_table, job_id=job_id, user_id=user_id, status="succeeded")

        result = await ledger.refund_if_not_succeeded(job_id, "10", job_table=job_table)

        assert result.applied is False
        assert result.skipped_reason == "succeeded"
        assert await _job_refund_applied(conn, job_table, job_id) is False
        balance = await ledger.get_balance(user_id)
        assert balance.balance == Decimal("10")


async def test_refund_waits_for_success_terminal_race(database_url: str) -> None:
    user_id = f"credit-race-{uuid4()}"
    job_id = uuid4()
    job_table = f"credit_test_jobs_{uuid4().hex}"
    locked = asyncio.Event()
    release = asyncio.Event()

    async with _connect(database_url) as setup_conn:
        await setup_credit_ledger(setup_conn)
        await _create_job_table(setup_conn, job_table)
        await CreditLedger(setup_conn).upsert_account(user_id, "10")
        await _insert_job(setup_conn, job_table, job_id=job_id, user_id=user_id, status="running")

    async def mark_succeeded_while_holding_row() -> None:
        async with _connect(database_url) as conn, conn.transaction():
            await conn.execute(
                sql.SQL("UPDATE {} SET status = 'succeeded' WHERE id = %s").format(
                    sql.Identifier(job_table)
                ),
                (job_id,),
            )
            locked.set()
            await release.wait()

    success_task = asyncio.create_task(mark_succeeded_while_holding_row())
    await locked.wait()

    async with _connect(database_url) as refund_conn:
        refund_task = asyncio.create_task(
            CreditLedger(refund_conn).refund_if_not_succeeded(
                job_id,
                "10",
                job_table=job_table,
            )
        )
        await asyncio.sleep(0.05)
        release.set()
        result = await asyncio.wait_for(refund_task, timeout=3)

    await success_task

    async with _connect(database_url) as verify_conn:
        ledger = CreditLedger(verify_conn)
        assert result.applied is False
        assert result.skipped_reason == "succeeded"
        assert await _job_refund_applied(verify_conn, job_table, job_id) is False
        balance = await ledger.get_balance(user_id)
        assert balance.balance == Decimal("10")
