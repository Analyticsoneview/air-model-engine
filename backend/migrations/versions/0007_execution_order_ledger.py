"""PostgreSQL schema for execution policy and durable idempotent order ledger."""
from alembic import op
import sqlalchemy as sa
revision = "0007_execution_order_ledger"
down_revision = "0006_market_data_source_registry"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("execution_policy",
        sa.Column("id",sa.SmallInteger(),primary_key=True),
        sa.Column("master_auto_enabled",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("strategy_json",sa.Text(),nullable=False,server_default="{}"),
        sa.Column("updated_at",sa.Text(),nullable=False),
        sa.CheckConstraint("id = 1",name="ck_execution_policy_singleton"))
    op.create_table("order_ledger",
        sa.Column("broker",sa.String(32),nullable=False),sa.Column("account_id",sa.String(128),nullable=False),
        sa.Column("idempotency_key",sa.String(128),nullable=False),sa.Column("broker_order_id",sa.String(128),nullable=False,server_default=""),
        sa.Column("status",sa.String(32),nullable=False),sa.Column("raw_json",sa.Text(),nullable=False),
        sa.Column("created_at",sa.Text(),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.Column("updated_at",sa.Text(),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.PrimaryKeyConstraint("broker","account_id","idempotency_key",name="pk_order_ledger"))
    op.create_index("idx_order_ledger_status","order_ledger",["status","updated_at"])
    op.create_table("order_ledger_events",
        sa.Column("event_id",sa.BigInteger(),sa.Identity(always=False),primary_key=True),
        sa.Column("broker",sa.String(32),nullable=False),sa.Column("account_id",sa.String(128),nullable=False),
        sa.Column("idempotency_key",sa.String(128),nullable=False),sa.Column("status",sa.String(32),nullable=False),
        sa.Column("broker_order_id",sa.String(128),nullable=False,server_default=""),
        sa.Column("raw_json",sa.Text(),nullable=False),
        sa.Column("event_at",sa.Text(),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP::text")))
    op.create_index("idx_order_events_account","order_ledger_events",["broker","account_id","event_id"])
def downgrade():
    op.drop_index("idx_order_events_account",table_name="order_ledger_events")
    op.drop_table("order_ledger_events")
    op.drop_index("idx_order_ledger_status",table_name="order_ledger")
    op.drop_table("order_ledger")
    op.drop_table("execution_policy")
