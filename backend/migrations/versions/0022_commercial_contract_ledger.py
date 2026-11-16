"""Create durable annual commercial contract and append-only lifecycle ledger.

Revision ID: 0022_commercial_contract_ledger
Revises: 0021_tenant_object_storage
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_commercial_contract_ledger"
down_revision = "0021_tenant_object_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_commercial_contracts",
        sa.Column("contract_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("billing_period", sa.String(16), nullable=False, server_default="ANNUAL"),
        sa.Column("currency", sa.String(3)),
        sa.Column("amount_minor", sa.BigInteger()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("grace_end_date", sa.Date()),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(64)),
        sa.Column("provider_customer_ref", sa.String(255)),
        sa.Column("provider_contract_ref", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("billing_period = 'ANNUAL'", name="ck_air_contract_annual_only"),
        sa.CheckConstraint("status IN ('DRAFT','TRIAL','ACTIVE','GRACE','PAST_DUE','CANCELLED','EXPIRED','SUSPENDED')", name="ck_air_contract_status"),
        sa.CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="ck_air_contract_amount_nonnegative"),
        sa.CheckConstraint("end_date > start_date", name="ck_air_contract_period_positive"),
    )
    op.create_index("ix_air_contract_tenant_status", "air_commercial_contracts", ["tenant_id", "status", "end_date"])
    op.create_table(
        "air_commercial_contract_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("air_commercial_contracts.contract_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(16)),
        sa.Column("to_status", sa.String(16)),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_contract_event_idempotency"),
    )
    op.create_index("ix_air_contract_events_history", "air_commercial_contract_events", ["tenant_id", "contract_id", "occurred_at"])
    for table in ("air_commercial_contracts", "air_commercial_contract_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_scope ON {table}
            USING (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))""")
    # Application role can read/insert events but cannot mutate or delete history.
    op.execute("REVOKE UPDATE, DELETE ON air_commercial_contract_events FROM PUBLIC")


def downgrade() -> None:
    for table in ("air_commercial_contract_events", "air_commercial_contracts"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_contract_events_history", table_name="air_commercial_contract_events")
    op.drop_table("air_commercial_contract_events")
    op.drop_index("ix_air_contract_tenant_status", table_name="air_commercial_contracts")
    op.drop_table("air_commercial_contracts")
