"""Complete customer lifecycle dates and append-only audit metadata.

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
    op.add_column("air_access_decision_history",
        sa.Column("authenticator_verified_at", sa.Text(), nullable=True))
    op.add_column("air_access_decision_history",
        sa.Column("verification_reference", sa.String(120), nullable=False, server_default=""))
    op.add_column("air_access_decision_history",
        sa.Column("request_context", sa.Text(), nullable=False, server_default="{}"))

    op.create_table(
        "air_customer_lifecycle",
        sa.Column("customer_id", sa.String(16), primary_key=True),
        sa.Column("first_registered_at", sa.Text(), nullable=False),
        sa.Column("first_approved_at", sa.Text(), nullable=True),
        sa.Column("first_rejected_at", sa.Text(), nullable=True),
        sa.Column("first_plan_availed_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
    )
    op.create_table(
        "air_customer_subscription_history",
        sa.Column("assignment_id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(16), nullable=False),
        sa.Column("plan_code", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("assigned_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.Column("assigned_by_admin_id", sa.String(36), nullable=False, server_default=""),
    )
    op.create_index("ix_air_customer_subscription_history_customer",
                    "air_customer_subscription_history", ["customer_id", "assigned_at"])

    op.execute("""
        INSERT INTO air_customer_lifecycle(customer_id, first_registered_at, first_approved_at, first_plan_availed_at)
        SELECT r.mobile_e164, MIN(r.created_at),
               (SELECT MIN(d.decided_at) FROM air_access_decision_history d
                 WHERE d.mobile_e164=r.mobile_e164 AND d.new_status='APPROVED'),
               (SELECT MIN(s.starts_at) FROM air_customer_subscriptions s
                 WHERE s.customer_id=r.mobile_e164)
          FROM air_access_requests r
         GROUP BY r.mobile_e164
        ON CONFLICT(customer_id) DO NOTHING
    """)
    op.execute("""
        CREATE FUNCTION air_reject_customer_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'AIR customer audit history is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table, trigger in (
        ("air_access_decision_history", "trg_air_access_decisions_append_only"),
        ("air_customer_subscription_history", "trg_air_subscription_history_append_only"),
    ):
        op.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION air_reject_customer_audit_mutation()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_air_subscription_history_append_only ON air_customer_subscription_history")
    op.execute("DROP TRIGGER IF EXISTS trg_air_access_decisions_append_only ON air_access_decision_history")
    op.execute("DROP FUNCTION IF EXISTS air_reject_customer_audit_mutation()")
    op.drop_index("ix_air_customer_subscription_history_customer", table_name="air_customer_subscription_history")
    op.drop_table("air_customer_subscription_history")
    op.drop_table("air_customer_lifecycle")
    op.drop_column("air_access_decision_history", "request_context")
    op.drop_column("air_access_decision_history", "verification_reference")
    op.drop_column("air_access_decision_history", "authenticator_verified_at")
