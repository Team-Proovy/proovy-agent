"""create video_jobs table

Revision ID: 20260531_0001
Revises:
Create Date: 2026-05-31
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260531_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("problem_hash", sa.Text(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retry_source_job_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("lease_holder_instance_id", sa.Text(), nullable=True),
        sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_attempt_id", sa.Text(), nullable=True),
        sa.Column("artifact_object_key", sa.Text(), nullable=True),
        sa.Column("error_stage", sa.Text(), nullable=True),
        sa.Column("user_error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "cost",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("cloud_tasks_name", sa.Text(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["retry_source_job_id"], ["video_jobs.id"]),
        sa.UniqueConstraint("cloud_tasks_name", name="uq_video_jobs_cloud_tasks_name"),
    )
    op.create_index(
        "uq_video_jobs_retry_source_job_id",
        "video_jobs",
        ["retry_source_job_id"],
        unique=True,
        postgresql_where=sa.text("retry_source_job_id IS NOT NULL"),
    )
    op.execute(
        "CREATE INDEX ix_video_jobs_thread_created ON video_jobs (thread_id, created_at DESC)"
    )
    op.create_index("ix_video_jobs_status", "video_jobs", ["status"])
    op.create_index("ix_video_jobs_problem_hash", "video_jobs", ["problem_hash"])
    op.create_index(
        "ix_video_jobs_status_progress_updated_at",
        "video_jobs",
        ["status", "progress_updated_at"],
    )
    op.execute(
        "CREATE INDEX ix_video_jobs_user_status_created "
        "ON video_jobs (user_id, status, created_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_video_jobs_user_status_created", table_name="video_jobs")
    op.drop_index("ix_video_jobs_status_progress_updated_at", table_name="video_jobs")
    op.drop_index("ix_video_jobs_problem_hash", table_name="video_jobs")
    op.drop_index("ix_video_jobs_status", table_name="video_jobs")
    op.drop_index("ix_video_jobs_thread_created", table_name="video_jobs")
    op.drop_index("uq_video_jobs_retry_source_job_id", table_name="video_jobs")
    op.drop_table("video_jobs")
