"""create unified credit ledger tables

Revision ID: 20260531_0001
Revises:
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260531_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
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
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_credit_holds_plan_id;
        DROP INDEX IF EXISTS idx_credit_holds_active;
        DROP TABLE IF EXISTS credit_holds;
        DROP TABLE IF EXISTS credits;
        """
    )
