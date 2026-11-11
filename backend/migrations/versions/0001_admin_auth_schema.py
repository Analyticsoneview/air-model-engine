"""Create versioned PostgreSQL schema for AIR administrator authentication.

Revision ID: 0001_admin_auth_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_admin_auth_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_admin_users",
        sa.Column("admin_id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("mfa_secret", sa.LargeBinary(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_totp_counter", sa.BigInteger(), nullable=False, server_default="-1"),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("role IN ('SUPER_ADMIN','ADMIN','RESEARCH_ADMIN')", name="ck_air_admin_users_role"),
        sa.UniqueConstraint(sa.text("lower(email)"), name="uq_air_admin_users_email_lower"),
    )
    op.create_table(
        "air_admin_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("admin_id", sa.String(36), sa.ForeignKey("air_admin_users.admin_id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_air_admin_sessions_admin_active", "air_admin_sessions", ["admin_id", "active"])
    op.create_table(
        "air_admin_login_limits",
        sa.Column("rate_key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started", sa.BigInteger(), nullable=False),
        sa.Column("locked_until", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "air_admin_audit",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("actor_admin_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_admin_id", sa.String(36), nullable=True),
        sa.Column("details", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_air_admin_audit_created_at", "air_admin_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_air_admin_audit_created_at", table_name="air_admin_audit")
    op.drop_table("air_admin_audit")
    op.drop_table("air_admin_login_limits")
    op.drop_index("ix_air_admin_sessions_admin_active", table_name="air_admin_sessions")
    op.drop_table("air_admin_sessions")
    op.drop_table("air_admin_users")
