"""Durable workflow run ledger.

Revision ID: 0013_workflow_run_ledger
Revises: 0012_workflow_engine_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_workflow_run_ledger"
down_revision = "0012_workflow_engine_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_workflow_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("execution_mode", sa.String(24), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("workflow_id", "workflow_version", "event_id",
                            name="uq_air_workflow_run_identity"),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')",
                           name="ck_air_workflow_run_status"),
    )
    op.create_index("ix_air_workflow_runs_status_time", "air_workflow_runs",
                    ["status", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_air_workflow_runs_status_time", table_name="air_workflow_runs")
    op.drop_table("air_workflow_runs")
