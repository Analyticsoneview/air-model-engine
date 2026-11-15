"""Complete customer lifecycle, subscription history and immutable approval audit.

Revision ID: 0009_customer_lifecycle_reporting
Revises: 0008_customer_access_decisions
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_customer_lifecycle_reporting"
down_revision = "0008_customer_access_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("air_access_decision_history", sa.Column("totp_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("air_access_decision_history", sa.Column("verification_reference", sa.String(36), nullable=True))
    op.add_column("air_access_decision_history", sa.Column("device_id", sa.String(128), nullable=True))
    op.add_column("air_access_decision_history", sa.Column("request_context", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")))

    op.create_table(
        "air_customer_lifecycle",
        sa.Column("customer_id", sa.String(16), primary_key=True),
        sa.Column("first_registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_plan_availed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_air_customer_lifecycle_registered", "air_customer_lifecycle", ["first_registered_at"])
    op.create_index("ix_air_customer_lifecycle_approved", "air_customer_lifecycle", ["first_approved_at"])
    op.create_index("ix_air_customer_lifecycle_plan", "air_customer_lifecycle", ["first_plan_availed_at"])

    op.create_table(
        "air_customer_subscription_history",
        sa.Column("assignment_id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(16), nullable=False),
        sa.Column("plan_code", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assigned_by_admin_id", sa.String(36), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("plan_code IN ('DAILY','MONTHLY','SIX_MONTHS','YEARLY')", name="ck_air_subscription_history_plan"),
        sa.CheckConstraint("status IN ('ACTIVE','CANCELLED','EXPIRED')", name="ck_air_subscription_history_status"),
    )
    op.create_index("ix_air_subscription_history_customer", "air_customer_subscription_history", ["customer_id", "assigned_at"])

    # Backfill identity lifecycle without treating each device request as a customer.
    op.execute("""
        INSERT INTO air_customer_lifecycle(customer_id, first_registered_at)
        SELECT mobile_e164, MIN(created_at::timestamptz)
        FROM air_access_requests GROUP BY mobile_e164
        ON CONFLICT(customer_id) DO NOTHING
    """)
    op.execute("""
        UPDATE air_customer_lifecycle l
        SET first_approved_at = x.first_approved_at
        FROM (
            SELECT mobile_e164, MIN(decided_at::timestamptz) AS first_approved_at
            FROM air_access_decision_history
            WHERE new_status='APPROVED'
            GROUP BY mobile_e164
        ) x WHERE x.mobile_e164=l.customer_id
    """)
    op.execute("""
        INSERT INTO air_customer_subscription_history
            (assignment_id, customer_id, plan_code, starts_at, expires_at, status, assigned_at)
        SELECT md5(customer_id || starts_at || expires_at), customer_id, plan_code,
               starts_at::timestamptz, expires_at::timestamptz, status, updated_at::timestamptz
        FROM air_customer_subscriptions
        ON CONFLICT(assignment_id) DO NOTHING
    """)
    op.execute("""
        UPDATE air_customer_lifecycle l SET first_plan_availed_at=x.first_plan_availed_at
        FROM (SELECT customer_id, MIN(assigned_at) AS first_plan_availed_at
              FROM air_customer_subscription_history GROUP BY customer_id) x
        WHERE x.customer_id=l.customer_id
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION air_reject_access_decision_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'air_access_decision_history is append-only';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_air_access_decision_immutable
        BEFORE UPDATE OR DELETE ON air_access_decision_history
        FOR EACH ROW EXECUTE FUNCTION air_reject_access_decision_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_air_access_decision_immutable ON air_access_decision_history")
    op.execute("DROP FUNCTION IF EXISTS air_reject_access_decision_mutation()")
    op.drop_index("ix_air_subscription_history_customer", table_name="air_customer_subscription_history")
    op.drop_table("air_customer_subscription_history")
    op.drop_index("ix_air_customer_lifecycle_plan", table_name="air_customer_lifecycle")
    op.drop_index("ix_air_customer_lifecycle_approved", table_name="air_customer_lifecycle")
    op.drop_index("ix_air_customer_lifecycle_registered", table_name="air_customer_lifecycle")
    op.drop_table("air_customer_lifecycle")
    op.drop_column("air_access_decision_history", "request_context")
    op.drop_column("air_access_decision_history", "device_id")
    op.drop_column("air_access_decision_history", "verification_reference")
    op.drop_column("air_access_decision_history", "totp_verified_at")
