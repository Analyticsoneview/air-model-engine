"""Append-only customer access decision history.

Revision ID: 0008_customer_access_decisions
Revises: 0007_execution_order_stores
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_customer_access_decisions"
down_revision = "0007_execution_order_stores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_access_decision_history",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("air_access_requests.request_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mobile_e164", sa.String(16), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=False),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("reviewer_admin_id", sa.String(36), nullable=False),
        sa.Column("reviewer_role", sa.String(32), nullable=False),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("totp_counter", sa.BigInteger(), nullable=False),
        sa.Column("decided_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.CheckConstraint("previous_status IN ('PENDING','APPROVED','REJECTED','BLOCKED')", name="ck_air_access_decision_previous"),
        sa.CheckConstraint("new_status IN ('APPROVED','REJECTED','BLOCKED')", name="ck_air_access_decision_new"),
        sa.CheckConstraint("reviewer_role IN ('SUPER_ADMIN','ADMIN')", name="ck_air_access_decision_role"),
    )
    op.create_index("ix_air_access_decisions_request", "air_access_decision_history", ["request_id", "decided_at"])
    op.create_index("ix_air_access_decisions_date", "air_access_decision_history", ["decided_at", "new_status"])


def downgrade() -> None:
    op.drop_index("ix_air_access_decisions_date", table_name="air_access_decision_history")
    op.drop_index("ix_air_access_decisions_request", table_name="air_access_decision_history")
    op.drop_table("air_access_decision_history")
