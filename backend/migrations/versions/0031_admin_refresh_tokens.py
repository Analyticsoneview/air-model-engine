"""Add hashed, rotating administrator refresh-token records.

Revision ID: 0031_admin_refresh_tokens
Revises: 0030_market_data_schema_isolation
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_admin_refresh_tokens"
down_revision = "0030_market_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_admin_refresh_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("air_admin_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_air_admin_refresh_session", "air_admin_refresh_tokens", ["session_id"])
    op.create_index("ix_air_admin_refresh_expiry", "air_admin_refresh_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_air_admin_refresh_expiry", table_name="air_admin_refresh_tokens")
    op.drop_index("ix_air_admin_refresh_session", table_name="air_admin_refresh_tokens")
    op.drop_table("air_admin_refresh_tokens")
