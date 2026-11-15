"""Customer-scoped portfolio snapshots and model-engine signal ledger.

Revision ID: 0010_portfolio_risk_foundation
Revises: 0009_customer_lifecycle
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_portfolio_risk_foundation"
down_revision = "0009_customer_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_portfolio_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("captured_at", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("positions_json", sa.Text(), nullable=False),
        sa.Column("holdings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
    )
    op.create_index("idx_air_portfolio_customer_time", "air_portfolio_snapshots",
                    ["customer_id", "captured_at"])
    op.create_index("idx_air_portfolio_account_time", "air_portfolio_snapshots",
                    ["customer_id", "broker", "account_id", "captured_at"])

    op.create_table(
        "model_signals",
        sa.Column("signal_id", sa.String(160), primary_key=True),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("signal_date", sa.String(10), nullable=False),
        sa.Column("entry_date", sa.String(10)),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_type", sa.String(16)),
        sa.Column("option_type", sa.String(2)),
        sa.Column("expiry", sa.String(10)),
        sa.Column("strike", sa.Float()),
        sa.Column("entry_price", sa.Float()),
        sa.Column("latest_price", sa.Float()),
        sa.Column("stop_loss", sa.Float()),
        sa.Column("target_1", sa.Float()),
        sa.Column("target_2", sa.Float()),
        sa.Column("target_3", sa.Float()),
        sa.Column("lot_size", sa.Integer()),
        sa.Column("quantity", sa.Integer()),
        sa.Column("score", sa.Float()),
        sa.Column("pnl", sa.Float()),
        sa.Column("pnl_pct", sa.Float()),
        sa.Column("shelf_life_days", sa.Integer()),
        sa.Column("valid_until", sa.String(10)),
        sa.Column("exit_date", sa.String(10)),
        sa.Column("exit_price", sa.Float()),
        sa.Column("achieved_target", sa.String(32)),
        sa.Column("reason", sa.Text()),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "classification IN ('NEW','HOLD','WAIT','RE-ENTRY','SL','TARGETS','EXPIRED','EXPIRYSCAN')",
            name="ck_model_signals_classification",
        ),
    )
    op.create_index("idx_model_signals_customer_status", "model_signals",
                    ["customer_id", "classification", "signal_date"])
    op.create_index("idx_model_signals_contract", "model_signals",
                    ["symbol", "expiry", "strike", "option_type"])

    op.create_table(
        "report_recipients",
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("verified", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("otp_hash", sa.String(64)),
        sa.Column("otp_expires_at", sa.Text()),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
    )
    op.create_table(
        "account_report_runs",
        sa.Column("run_id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("report_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.UniqueConstraint("customer_id", "broker", "account_id", "report_date",
                            name="uq_account_report_customer_account_date"),
    )
    op.create_index("idx_account_report_runs_customer_date", "account_report_runs",
                    ["customer_id", "report_date"])


def downgrade() -> None:
    op.drop_index("idx_account_report_runs_customer_date", table_name="account_report_runs")
    op.drop_table("account_report_runs")
    op.drop_table("report_recipients")
    op.drop_index("idx_model_signals_contract", table_name="model_signals")
    op.drop_index("idx_model_signals_customer_status", table_name="model_signals")
    op.drop_table("model_signals")
    op.drop_index("idx_air_portfolio_account_time", table_name="air_portfolio_snapshots")
    op.drop_index("idx_air_portfolio_customer_time", table_name="air_portfolio_snapshots")
    op.drop_table("air_portfolio_snapshots")
