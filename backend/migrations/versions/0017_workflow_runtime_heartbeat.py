"""Workflow worker heartbeat and runtime observability.

Revision ID: 0017_workflow_runtime_heartbeat
Revises: 0016_workflow_audit_calendar
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_workflow_runtime_heartbeat"
down_revision = "0016_workflow_audit_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_workflow_worker_heartbeats",
        sa.Column("worker_id", sa.String(160), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("last_seen", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", "component"),
        sa.CheckConstraint("status IN ('STARTING','RUNNING','DEGRADED','STOPPING')",
                           name="ck_air_workflow_worker_heartbeat_status"),
    )
    op.create_index("ix_air_workflow_worker_heartbeat_seen",
                    "air_workflow_worker_heartbeats", ["last_seen"])


def downgrade() -> None:
    op.drop_index("ix_air_workflow_worker_heartbeat_seen",
                  table_name="air_workflow_worker_heartbeats")
    op.drop_table("air_workflow_worker_heartbeats")
