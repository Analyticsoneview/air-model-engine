"""Add tenant-scoped usage events, aggregate counters and quota overrides.

Revision ID: 0023_usage_metering_quotas
Revises: 0022_commercial_contract_ledger
"""
from alembic import op
import sqlalchemy as sa
revision="0023_usage_metering_quotas"
down_revision="0022_commercial_contract_ledger"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("air_usage_events",
        sa.Column("event_id",sa.String(36),primary_key=True),
        sa.Column("tenant_id",sa.String(36),sa.ForeignKey("air_tenants.tenant_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("customer_id",sa.String(128),nullable=False),sa.Column("metric",sa.String(32),nullable=False),
        sa.Column("quantity",sa.BigInteger(),nullable=False),sa.Column("unit",sa.String(16),nullable=False),
        sa.Column("period",sa.String(16),nullable=False),sa.Column("period_start",sa.Date(),nullable=False),
        sa.Column("period_end",sa.Date(),nullable=False),sa.Column("event_type",sa.String(16),nullable=False,server_default="METERED"),
        sa.Column("status",sa.String(16),nullable=False),sa.Column("idempotency_key",sa.String(200),nullable=False),
        sa.Column("actor_id",sa.String(128),nullable=False),sa.Column("metadata_json",sa.JSON(),nullable=False,server_default=sa.text("'{}'::json")),
        sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id","idempotency_key",name="uq_air_usage_event_idempotency"),
        sa.CheckConstraint("metric IN ('api_calls','compute_seconds','storage_bytes','seats','licensed_data_bytes')",name="ck_air_usage_metric"),
        sa.CheckConstraint("quantity <> 0",name="ck_air_usage_quantity_nonzero"),
        sa.CheckConstraint("period IN ('DAILY','MONTHLY','ANNUAL')",name="ck_air_usage_period"),
        sa.CheckConstraint("status IN ('ACCEPTED','REJECTED')",name="ck_air_usage_status"),
        sa.CheckConstraint("event_type IN ('METERED','ADJUSTMENT')",name="ck_air_usage_event_type"))
    op.create_index("ix_air_usage_events_tenant_metric_period","air_usage_events",["tenant_id","metric","period","period_start","occurred_at"])
    op.create_table("air_usage_counters",
        sa.Column("tenant_id",sa.String(36),sa.ForeignKey("air_tenants.tenant_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("metric",sa.String(32),nullable=False),sa.Column("period",sa.String(16),nullable=False),
        sa.Column("period_start",sa.Date(),nullable=False),sa.Column("period_end",sa.Date(),nullable=False),
        sa.Column("quantity",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id","metric","period","period_start",name="pk_air_usage_counters"),
        sa.CheckConstraint("quantity >= 0",name="ck_air_usage_counter_nonnegative"))
    op.create_table("air_usage_quota_overrides",
        sa.Column("tenant_id",sa.String(36),sa.ForeignKey("air_tenants.tenant_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("metric",sa.String(32),nullable=False),sa.Column("period",sa.String(16),nullable=False),
        sa.Column("soft_limit",sa.BigInteger()),sa.Column("hard_limit",sa.BigInteger()),
        sa.Column("updated_by",sa.String(128),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id","metric","period",name="pk_air_usage_quota_overrides"),
        sa.CheckConstraint("metric IN ('api_calls','compute_seconds','storage_bytes','seats','licensed_data_bytes')",name="ck_air_usage_override_metric"),
        sa.CheckConstraint("period IN ('DAILY','MONTHLY','ANNUAL')",name="ck_air_usage_override_period"),
        sa.CheckConstraint("soft_limit IS NULL OR soft_limit >= 0",name="ck_air_usage_override_soft_nonnegative"),
        sa.CheckConstraint("hard_limit IS NULL OR hard_limit >= 0",name="ck_air_usage_override_hard_nonnegative"),
        sa.CheckConstraint("soft_limit IS NULL OR hard_limit IS NULL OR soft_limit <= hard_limit",name="ck_air_usage_override_order"))
    for table in ("air_usage_events","air_usage_counters","air_usage_quota_overrides"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_scope ON {table}
            USING (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))""")
    op.execute("REVOKE UPDATE, DELETE ON air_usage_events FROM PUBLIC")

def downgrade():
    for table in ("air_usage_quota_overrides","air_usage_counters","air_usage_events"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("air_usage_quota_overrides")
    op.drop_table("air_usage_counters")
    op.drop_index("ix_air_usage_events_tenant_metric_period",table_name="air_usage_events")
    op.drop_table("air_usage_events")
