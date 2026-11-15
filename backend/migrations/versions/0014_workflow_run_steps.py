"""Persisted workflow execution steps.

Revision ID: 0014_workflow_run_steps
Revises: 0013_workflow_run_ledger
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_workflow_run_steps"
down_revision = "0013_workflow_run_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_workflow_run_steps",
        sa.Column("step_record_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_json", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.Text()),
        sa.Column("completed_at", sa.Text()),
        sa.UniqueConstraint("run_id", "step_key", name="uq_air_workflow_run_step_key"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED')",
                           name="ck_air_workflow_run_step_status"),
        sa.CheckConstraint("step_index >= 0", name="ck_air_workflow_run_step_index"),
        sa.CheckConstraint("attempts >= 0", name="ck_air_workflow_run_step_attempts"),
    )
    op.create_index("ix_air_workflow_run_steps_order", "air_workflow_run_steps",
                    ["run_id", "step_index"])


def downgrade() -> None:
    op.drop_index("ix_air_workflow_run_steps_order", table_name="air_workflow_run_steps")
    op.drop_table("air_workflow_run_steps")
