"""Verified exchange calendar coverage and official NSE 2026 seed.

Revision ID: 0017_exchange_calendar_coverage
Revises: 0016_workflow_audit_calendar
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_exchange_calendar_coverage"
down_revision = "0016_workflow_audit_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_exchange_calendar_coverage",
        sa.Column("exchange_code", sa.String(8), nullable=False),
        sa.Column("calendar_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(240), nullable=False),
        sa.Column("verified_by", sa.String(128), nullable=False),
        sa.Column("verified_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("exchange_code", "calendar_year",
                                name="pk_air_exchange_calendar_coverage"),
        sa.CheckConstraint("status IN ('VERIFIED','INCOMPLETE')",
                           name="ck_air_exchange_calendar_coverage_status"),
    )
    holidays = [
        ("2026-01-15", "Municipal Corporation Election - Maharashtra"),
        ("2026-01-26", "Republic Day"),
        ("2026-02-15", "Mahashivratri (weekend holiday)"),
        ("2026-03-03", "Holi"),
        ("2026-03-21", "Id-Ul-Fitr (weekend holiday)"),
        ("2026-03-26", "Shri Ram Navami"),
        ("2026-03-31", "Shri Mahavir Jayanti"),
        ("2026-04-03", "Good Friday"),
        ("2026-04-14", "Dr. Baba Saheb Ambedkar Jayanti"),
        ("2026-05-01", "Maharashtra Day"),
        ("2026-05-28", "Bakri Id"),
        ("2026-06-26", "Muharram"),
        ("2026-08-15", "Independence Day (weekend holiday)"),
        ("2026-09-14", "Ganesh Chaturthi"),
        ("2026-10-02", "Mahatma Gandhi Jayanti"),
        ("2026-10-20", "Dussehra"),
        ("2026-11-08", "Diwali Laxmi Pujan - Muhurat session times notified separately"),
        ("2026-11-10", "Diwali-Balipratipada"),
        ("2026-11-24", "Prakash Gurpurb Sri Guru Nanak Dev"),
        ("2026-12-25", "Christmas"),
    ]
    op.bulk_insert(
        sa.table(
            "air_exchange_calendar",
            sa.column("exchange_code", sa.String(8)),
            sa.column("session_date", sa.String(10)),
            sa.column("status", sa.String(20)),
            sa.column("description", sa.String(240)),
            sa.column("session_open", sa.String(5)),
            sa.column("session_close", sa.String(5)),
            sa.column("source", sa.String(240)),
            sa.column("updated_by", sa.String(128)),
            sa.column("updated_at", sa.Text()),
        ),
        [{
            "exchange_code": "NSE", "session_date": date, "status": "HOLIDAY",
            "description": description, "session_open": None, "session_close": None,
            "source": "NSE official equity holiday calendar 2026",
            "updated_by": "system-seed", "updated_at": "2026-11-16T00:00:00+00:00",
        } for date, description in holidays],
    )
    op.bulk_insert(
        sa.table(
            "air_exchange_calendar_coverage",
            sa.column("exchange_code", sa.String(8)),
            sa.column("calendar_year", sa.Integer()),
            sa.column("status", sa.String(16)),
            sa.column("source", sa.String(240)),
            sa.column("verified_by", sa.String(128)),
            sa.column("verified_at", sa.Text()),
        ),
        [{
            "exchange_code": "NSE", "calendar_year": 2026, "status": "VERIFIED",
            "source": "NSE official equity holiday calendar 2026",
            "verified_by": "system-seed", "verified_at": "2026-11-16T00:00:00+00:00",
        }],
    )


def downgrade() -> None:
    op.drop_table("air_exchange_calendar_coverage")
    op.execute("DELETE FROM air_exchange_calendar WHERE exchange_code='NSE' AND source='NSE official equity holiday calendar 2026'")
