"""Workflow audit trail and exchange trading calendar.

Revision ID: 0016_workflow_audit_exchange_calendar
Revises: 0015_workflow_def_versions
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_workflow_audit_calendar"
down_revision = "0015_workflow_def_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_workflow_audit",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_air_workflow_audit_workflow_time",
        "air_workflow_audit", ["workflow_id", "created_at"],
    )
    op.create_table(
        "air_exchange_calendar",
        sa.Column("exchange_code", sa.String(8), nullable=False),
        sa.Column("session_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("description", sa.String(240), nullable=False, server_default=""),
        sa.Column("session_open", sa.String(5)),
        sa.Column("session_close", sa.String(5)),
        sa.Column("source", sa.String(240), nullable=False, server_default="ADMIN"),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("exchange_code", "session_date",
                                name="pk_air_exchange_calendar"),
        sa.CheckConstraint("status IN ('HOLIDAY','SPECIAL_SESSION','TRADING_DAY')",
                           name="ck_air_exchange_calendar_status"),
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION air_workflow_audit_reject_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $
        BEGIN
            RAISE EXCEPTION 'AIR workflow audit is append-only';
        END;
        $;
        CREATE TRIGGER trg_air_workflow_audit_no_update
            BEFORE UPDATE ON air_workflow_audit
            FOR EACH ROW EXECUTE FUNCTION air_workflow_audit_reject_mutation();
        CREATE TRIGGER trg_air_workflow_audit_no_delete
            BEFORE DELETE ON air_workflow_audit
            FOR EACH ROW EXECUTE FUNCTION air_workflow_audit_reject_mutation();
    """)
    op.create_index(
        "ix_air_exchange_calendar_date",
        "air_exchange_calendar", ["session_date", "exchange_code"],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_air_workflow_audit_no_update ON air_workflow_audit")
    op.execute("DROP TRIGGER IF EXISTS trg_air_workflow_audit_no_delete ON air_workflow_audit")
    op.execute("DROP FUNCTION IF EXISTS air_workflow_audit_reject_mutation()")
    op.drop_index("ix_air_exchange_calendar_date", table_name="air_exchange_calendar")
    op.drop_table("air_exchange_calendar")
    op.drop_index("ix_air_workflow_audit_workflow_time", table_name="air_workflow_audit")
    op.drop_table("air_workflow_audit")
