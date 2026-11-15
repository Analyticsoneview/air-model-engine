"""Customer-isolated support tickets and immutable ticket activity.
Revision ID: 0011_admin_support_center
Revises: 0010_portfolio_risk_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_admin_support_center"
down_revision = "0010_portfolio_risk_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_support_tickets",
        sa.Column("ticket_id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(120), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="OPEN"),
        sa.Column("priority", sa.String(12), nullable=False, server_default="NORMAL"),
        sa.Column("assigned_admin_id", sa.String(36)),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("category IN ('ACCOUNT','BILLING','BROKER','TECHNICAL','GENERAL')",
                           name="ck_air_support_ticket_category"),
        sa.CheckConstraint("status IN ('OPEN','IN_PROGRESS','WAITING_CUSTOMER','RESOLVED','CLOSED')",
                           name="ck_air_support_ticket_status"),
        sa.CheckConstraint("priority IN ('LOW','NORMAL','HIGH','URGENT')",
                           name="ck_air_support_ticket_priority"),
    )
    op.create_index("ix_air_support_customer_updated", "air_support_tickets", ["customer_id","updated_at"])
    op.create_index("ix_air_support_status_updated", "air_support_tickets", ["status","updated_at"])
    op.create_table(
        "air_support_ticket_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("actor_type", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_air_support_events_ticket", "air_support_ticket_events", ["ticket_id","created_at"])
    op.execute("""
        CREATE OR REPLACE FUNCTION air_reject_support_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'air_support_ticket_events is append-only';
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_air_support_events_immutable
        BEFORE UPDATE OR DELETE ON air_support_ticket_events
        FOR EACH ROW EXECUTE FUNCTION air_reject_support_event_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_air_support_events_immutable ON air_support_ticket_events")
    op.execute("DROP FUNCTION IF EXISTS air_reject_support_event_mutation()")
    op.drop_index("ix_air_support_events_ticket", table_name="air_support_ticket_events")
    op.drop_table("air_support_ticket_events")
    op.drop_index("ix_air_support_status_updated", table_name="air_support_tickets")
    op.drop_index("ix_air_support_customer_updated", table_name="air_support_tickets")
    op.drop_table("air_support_tickets")
