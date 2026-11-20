"""Add customer-scoped six-digit AIR PIN credentials and audit.

Revision ID: 0033_customer_pin_auth
Revises: 0032_customer_commercial_types
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_customer_pin_auth"
down_revision = "0032_customer_commercial_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_customer_pin_credentials",
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("pin_hash", sa.Text(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("must_reset", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reset_by_admin_id", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "air_customer_pin_audit",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_admin_id", sa.String(128), nullable=True),
        sa.Column("details", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for table in ("air_customer_pin_credentials", "air_customer_pin_audit"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY air_tenant_scope ON {table}
            USING (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
        """)
        op.execute(f"""
            CREATE TRIGGER trg_{table}_assign_tenant
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION air_assign_tenant_id()
        """)


def downgrade() -> None:
    for table in ("air_customer_pin_audit", "air_customer_pin_credentials"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_assign_tenant ON {table}")
        op.execute(f"DROP POLICY IF EXISTS air_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_table(table)
