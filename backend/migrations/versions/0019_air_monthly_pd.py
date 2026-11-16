"""AIR MPDSM monthly cycle and immutable dated snapshots.
Revision ID: 0019_air_monthly_pd
Revises: 0018_workflow_run_leases
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_air_monthly_pd"
down_revision = "0018_workflow_run_leases"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "air_monthly_pd_cycles",
        sa.Column("cycle_id", sa.String(64), primary_key=True),
        sa.Column("instrument_type", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("cycle_month", sa.String(7), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("previous_month_pml", sa.Numeric(20,6), nullable=False),
        sa.Column("previous_month_pmh", sa.Numeric(20,6), nullable=False),
        sa.Column("equilibrium", sa.Numeric(20,6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instrument_type","symbol","cycle_month",name="uq_air_monthly_pd_cycle"))
    op.create_index("ix_air_monthly_pd_cycle_month","air_monthly_pd_cycles",["cycle_month","instrument_type"])
    op.create_table(
        "air_monthly_pd_snapshots",
        sa.Column("snapshot_id",sa.String(64),primary_key=True),
        sa.Column("cycle_id",sa.String(64),sa.ForeignKey("air_monthly_pd_cycles.cycle_id",ondelete="CASCADE"),nullable=False),
        sa.Column("as_of_date",sa.Date(),nullable=False),
        sa.Column("snapshot_type",sa.String(32),nullable=False),
        sa.Column("support_status",sa.String(32),nullable=False),
        sa.Column("pattern",sa.String(24),nullable=False),
        sa.Column("pattern_state",sa.String(24),nullable=False),
        sa.Column("expiry_metadata",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
        sa.Column("evidence",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
        sa.Column("forecast",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
        sa.Column("actual",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("cycle_id","as_of_date","snapshot_type",name="uq_air_monthly_pd_snapshot"))
    op.create_index("ix_air_monthly_pd_snapshot_date","air_monthly_pd_snapshots",["as_of_date","snapshot_type"])

def downgrade() -> None:
    op.drop_index("ix_air_monthly_pd_snapshot_date",table_name="air_monthly_pd_snapshots")
    op.drop_table("air_monthly_pd_snapshots")
    op.drop_index("ix_air_monthly_pd_cycle_month",table_name="air_monthly_pd_cycles")
    op.drop_table("air_monthly_pd_cycles")
