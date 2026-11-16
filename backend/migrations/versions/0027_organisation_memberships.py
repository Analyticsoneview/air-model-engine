"""Organisation membership, invitations, seat reservations and audit.

Revision ID: 0027_organisation_memberships
Revises: 0026_customer_onboarding
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_organisation_memberships"
down_revision = "0026_customer_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Membership is tenant-scoped; one customer may participate in more than one
    # organisation. The existing composite primary key remains authoritative.
    op.drop_constraint("air_tenant_members_customer_id_key", "air_tenant_members", type_="unique")
    op.create_index(
        "ix_air_tenant_members_customer_status",
        "air_tenant_members",
        ["customer_id", "status"],
    )
    op.create_table(
        "air_tenant_invitations",
        sa.Column("invitation_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("invited_customer_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("invited_by", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_tenant_invitation_idempotency"),
        sa.CheckConstraint("role IN ('ADMIN','MEMBER','READ_ONLY')", name="ck_air_tenant_invitation_role"),
        sa.CheckConstraint("status IN ('PENDING','ACCEPTED','REVOKED','EXPIRED')", name="ck_air_tenant_invitation_status"),
    )
    op.create_index(
        "ix_air_tenant_invitations_tenant_status_expiry",
        "air_tenant_invitations",
        ["tenant_id", "status", "expires_at"],
    )
    op.create_index(
        "uq_air_tenant_invitation_pending_customer",
        "air_tenant_invitations",
        ["tenant_id", "invited_customer_id"],
        unique=True,
        postgresql_where=sa.text("status='PENDING'"),
    )
    op.create_table(
        "air_tenant_membership_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("air_tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("from_role", sa.String(16)),
        sa.Column("to_role", sa.String(16)),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_air_tenant_membership_event_idempotency"),
        sa.CheckConstraint(
            "event_type IN ('INVITED','INVITATION_ACCEPTED','INVITATION_REVOKED','ROLE_CHANGED','MEMBER_REMOVED','ADMIN_MEMBER_ADDED')",
            name="ck_air_tenant_membership_event_type",
        ),
    )
    op.create_index(
        "ix_air_tenant_membership_events_customer_time",
        "air_tenant_membership_events",
        ["tenant_id", "customer_id", "occurred_at"],
    )
    for table in ("air_tenant_invitations", "air_tenant_membership_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_scope ON {table}
            USING (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))
            WITH CHECK (air_is_admin_context()
                OR tenant_id=NULLIF(current_setting('air.tenant_id',true),''))""")
    op.execute("REVOKE UPDATE, DELETE ON air_tenant_membership_events FROM PUBLIC")


def downgrade() -> None:
    for table in ("air_tenant_membership_events", "air_tenant_invitations"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_scope ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_air_tenant_membership_events_customer_time", table_name="air_tenant_membership_events")
    op.drop_table("air_tenant_membership_events")
    op.drop_index("uq_air_tenant_invitation_pending_customer", table_name="air_tenant_invitations")
    op.drop_index("ix_air_tenant_invitations_tenant_status_expiry", table_name="air_tenant_invitations")
    op.drop_table("air_tenant_invitations")
    op.drop_index("ix_air_tenant_members_customer_status", table_name="air_tenant_members")
    # Downgrade is intentionally blocked once a customer has multiple memberships.
    op.execute("""DO $air$ BEGIN
        IF EXISTS (SELECT customer_id FROM air_tenant_members
                   WHERE status <> 'REMOVED' GROUP BY customer_id HAVING COUNT(*) > 1) THEN
            RAISE EXCEPTION 'Cannot restore global customer membership uniqueness while multi-organisation memberships exist';
        END IF;
    END $air$""")
    op.create_unique_constraint("air_tenant_members_customer_id_key", "air_tenant_members", ["customer_id"])
