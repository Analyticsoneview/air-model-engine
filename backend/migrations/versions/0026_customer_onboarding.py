"""Customer onboarding, explicit consent and trial lifecycle.

Revision ID: 0026_customer_onboarding
Revises: 0025_billing_recon
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_customer_onboarding"
down_revision = "0025_billing_recon"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "air_customer_onboarding",
        sa.Column("onboarding_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("trial_started_at", sa.DateTime(timezone=True)),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.Column("contract_id", sa.String(36)),
        sa.Column("cancel_reason", sa.String(500)),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "customer_id", "product_code", name="uq_air_onboarding_customer_product"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_onboarding_idempotency"),
        sa.CheckConstraint("status IN ('PENDING','TRIAL','ACTIVE','CANCELLED','EXPIRED','REJECTED')", name="ck_air_onboarding_status"),
        sa.CheckConstraint("(status <> 'TRIAL') OR (trial_started_at IS NOT NULL AND trial_ends_at > trial_started_at)", name="ck_air_onboarding_trial_dates"),
    )
    op.create_index("ix_air_onboarding_tenant_status", "air_customer_onboarding", ["tenant_id", "status", "updated_at"])
    op.create_table(
        "air_customer_consents",
        sa.Column("consent_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("consent_type", sa.String(32), nullable=False),
        sa.Column("document_version", sa.String(64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_consent_idempotency"),
        sa.CheckConstraint("consent_type IN ('TERMS','PRIVACY','DATA_PROCESSING','MARKETING')", name="ck_air_consent_type"),
    )
    op.create_index("ix_air_consents_customer", "air_customer_consents", ["tenant_id", "customer_id", "consent_type", "accepted_at"])
    op.create_table(
        "air_customer_onboarding_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("onboarding_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("from_status", sa.String(16)),
        sa.Column("to_status", sa.String(16)),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id", "onboarding_id"], ["air_customer_onboarding.tenant_id", "air_customer_onboarding.onboarding_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_onboarding_event_idempotency"),
    )
    op.create_index("ix_air_onboarding_event_history", "air_customer_onboarding_events", ["tenant_id", "onboarding_id", "occurred_at"])
    for table in ("air_customer_onboarding", "air_customer_consents", "air_customer_onboarding_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_scope ON {table}
            USING (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))""")
    op.execute("REVOKE UPDATE, DELETE ON air_customer_consents FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON air_customer_onboarding_events FROM PUBLIC")


def downgrade():
    for table in ("air_customer_onboarding_events", "air_customer_consents", "air_customer_onboarding"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_onboarding_event_history", table_name="air_customer_onboarding_events")
    op.drop_table("air_customer_onboarding_events")
    op.drop_index("ix_air_consents_customer", table_name="air_customer_consents")
    op.drop_table("air_customer_consents")
    op.drop_index("ix_air_onboarding_tenant_status", table_name="air_customer_onboarding")
    op.drop_table("air_customer_onboarding")
