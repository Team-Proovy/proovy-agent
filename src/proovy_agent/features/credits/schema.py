"""DDL helpers for the unified credit ledger."""

from typing import Any

from psycopg import AsyncConnection

CREDIT_LEDGER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS credits (
    user_id TEXT PRIMARY KEY,
    balance NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS credit_holds (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES credits(user_id) ON DELETE CASCADE,
    amount NUMERIC NOT NULL CHECK (amount >= 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'captured', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    plan_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_credit_holds_active
    ON credit_holds (user_id, status, expires_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_credit_holds_plan_id
    ON credit_holds (plan_id)
    WHERE plan_id IS NOT NULL;
"""


async def setup_credit_ledger(conn: AsyncConnection[Any]) -> None:
    """Create credit ledger tables and indexes if they do not exist."""
    async with conn.transaction():
        await conn.execute(CREDIT_LEDGER_SCHEMA_SQL)
