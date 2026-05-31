"""create unified credit ledger tables

Revision ID: 20260531_0001
Revises:
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from alembic import op

from proovy_agent.features.credits.schema import CREDIT_LEDGER_SCHEMA_SQL

revision: str = "20260531_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(CREDIT_LEDGER_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_credit_holds_plan_id;
        DROP INDEX IF EXISTS idx_credit_holds_active;
        DROP TABLE IF EXISTS credit_holds;
        DROP TABLE IF EXISTS credits;
        """
    )
