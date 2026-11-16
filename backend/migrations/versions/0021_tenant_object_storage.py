"""Add tenant-scoped object storage accounting and immutable object metadata.

Revision ID: 0021_tenant_object_storage
Revises: 0020_saas_tenant_isolation
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_tenant_object_storage"
down_revision = "0020_saas_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "air_tenants",
        sa.Column("storage_used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_air_tenants_storage_used_nonnegative",
        "air_tenants",
        "storage_used_bytes >= 0",
    )
    op.create_table(
        "air_tenant_objects",
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False, server_default="application/octet-stream"),
        sa.Column("etag", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("tenant_id", "object_key", name="pk_air_tenant_objects"),
        sa.CheckConstraint("size_bytes > 0", name="ck_air_tenant_objects_size_positive"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_air_tenant_objects_sha256_length"),
        sa.CheckConstraint("status IN ('PENDING','STORED')", name="ck_air_tenant_objects_status"),
    )
    op.create_index("ix_air_tenant_objects_status_created", "air_tenant_objects", ["tenant_id", "status", "created_at"])
    op.execute("ALTER TABLE air_tenant_objects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE air_tenant_objects FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY air_tenant_objects_scope ON air_tenant_objects
        USING (air_is_admin_context()
            OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
        WITH CHECK (air_is_admin_context()
            OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
    """)
    # Customer requests may reserve quota only for their own active tenant.
    # The application uses this policy only for the storage_used_bytes update.
    op.execute("""
        CREATE POLICY air_tenants_storage_update ON air_tenants FOR UPDATE
        USING (tenant_id=NULLIF(current_setting('air.tenant_id',true),'')
            AND status='ACTIVE')
        WITH CHECK (tenant_id=NULLIF(current_setting('air.tenant_id',true),'')
            AND status='ACTIVE')
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS air_tenants_storage_update ON air_tenants")
    op.execute("DROP POLICY IF EXISTS air_tenant_objects_scope ON air_tenant_objects")
    op.execute("ALTER TABLE air_tenant_objects NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE air_tenant_objects DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_tenant_objects_status_created", table_name="air_tenant_objects")
    op.drop_table("air_tenant_objects")
    op.drop_constraint("ck_air_tenants_storage_used_nonnegative", "air_tenants", type_="check")
    op.drop_column("air_tenants", "storage_used_bytes")
