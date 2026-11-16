"""Enterprise licences bound to registered AIR deployment instances.

Revision ID: 0028_enterprise_license
Revises: 0027_organisation_memberships
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_enterprise_license"
down_revision = "0027_organisation_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_deployment_instances",
        sa.Column("deployment_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("instance_key", sa.String(128), nullable=False),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("tenancy", sa.String(16), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "instance_key", name="uq_air_deployment_tenant_instance"),
        sa.UniqueConstraint("tenant_id", "deployment_id", name="uq_air_deployment_tenant_id"),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','RETIRED')", name="ck_air_deployment_status"),
        sa.CheckConstraint("provider IN ('on_prem','aws')", name="ck_air_deployment_provider"),
        sa.CheckConstraint("tenancy IN ('single','multi')", name="ck_air_deployment_tenancy"),
    )
    op.create_table(
        "air_enterprise_licenses",
        sa.Column("license_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("contract_id", sa.String(36), nullable=False),
        sa.Column("license_code", sa.String(64), nullable=False, unique=True),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("max_seats", sa.Integer(), nullable=False),
        sa.Column("max_deployments", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("allowed_profiles", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("grace_until", sa.Date()),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id","contract_id"], ["air_commercial_contracts.tenant_id","air_commercial_contracts.contract_id"], ondelete="RESTRICT", name="fk_air_license_tenant_contract"),
        sa.UniqueConstraint("tenant_id", "license_id", name="uq_air_license_tenant_id"),
        sa.CheckConstraint("status IN ('ACTIVE','GRACE','SUSPENDED','REVOKED','EXPIRED')", name="ck_air_license_status"),
        sa.CheckConstraint("max_seats > 0 AND max_deployments > 0", name="ck_air_license_limits"),
        sa.CheckConstraint("valid_until > valid_from", name="ck_air_license_dates"),
    )
    op.create_table(
        "air_license_bindings",
        sa.Column("binding_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("license_id", sa.String(36), nullable=False),
        sa.Column("deployment_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("unbound_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id","license_id"], ["air_enterprise_licenses.tenant_id","air_enterprise_licenses.license_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id","deployment_id"], ["air_deployment_instances.tenant_id","air_deployment_instances.deployment_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("license_id","deployment_id", name="uq_air_license_deployment_binding"),
        sa.UniqueConstraint("tenant_id","idempotency_key", name="uq_air_license_binding_idempotency"),
        sa.CheckConstraint("status IN ('ACTIVE','UNBOUND','REVOKED')", name="ck_air_license_binding_status"),
    )
    op.create_table(
        "air_enterprise_license_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("license_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id","license_id"], ["air_enterprise_licenses.tenant_id","air_enterprise_licenses.license_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id","idempotency_key", name="uq_air_enterprise_license_event_idempotency"),
    )
    for table in ("air_deployment_instances","air_enterprise_licenses","air_license_bindings","air_enterprise_license_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_scope ON {table}
            USING (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context() OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))""")
    op.execute("REVOKE UPDATE, DELETE ON air_enterprise_license_events FROM PUBLIC")


def downgrade() -> None:
    for table in ("air_enterprise_license_events","air_license_bindings","air_enterprise_licenses","air_deployment_instances"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("air_enterprise_license_events")
    op.drop_table("air_license_bindings")
    op.drop_table("air_enterprise_licenses")
    op.drop_table("air_deployment_instances")
