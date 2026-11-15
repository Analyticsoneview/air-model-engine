"""Add atomic workflow run ownership and recoverable execution leases.

Revision ID: 0018_workflow_run_leases
Revises: 0017_workflow_runtime_heartbeat
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_workflow_run_leases"
down_revision = "0017_workflow_runtime_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("air_workflow_runs", sa.Column("claimed_by", sa.String(160), nullable=True))
    op.add_column("air_workflow_runs", sa.Column("claimed_at", sa.Text(), nullable=True))
    op.add_column("air_workflow_runs", sa.Column("lease_expires_at", sa.Text(), nullable=True))
    op.add_column(
        "air_workflow_runs",
        sa.Column("claim_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_air_workflow_runs_lease",
        "air_workflow_runs",
        ["status", "lease_expires_at", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_air_workflow_runs_lease", table_name="air_workflow_runs")
    op.drop_column("air_workflow_runs", "claim_version")
    op.drop_column("air_workflow_runs", "lease_expires_at")
    op.drop_column("air_workflow_runs", "claimed_at")
    op.drop_column("air_workflow_runs", "claimed_by")
