"""Create isolated PostgreSQL schemas for AIR market-data domains.
Revision ID: 0030_market_schema
Revises: 0029_customer_credentials
"""
from alembic import op

revision = "0030_market_schema"
down_revision = "0029_customer_credentials"
branch_labels = None
depends_on = None

MARKET_SCHEMAS = ("nse_cm", "nse_fo", "nse_com", "nse_cd", "us_market")


def upgrade() -> None:
    # Create every namespace before creating schema-qualified objects.
    for schema in (*MARKET_SCHEMAS, "market_ref", "ingestion", "research"):
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    op.execute("""
        CREATE TABLE ingestion.feed_runs (
            run_id UUID PRIMARY KEY,
            feed_key VARCHAR(48) NOT NULL,
            dataset_key VARCHAR(96) NOT NULL,
            run_mode VARCHAR(24) NOT NULL CHECK (run_mode IN ('bootstrap','incremental','backfill','refresh')),
            status VARCHAR(24) NOT NULL CHECK (status IN ('queued','running','partial','succeeded','failed','cancelled')),
            requested_from DATE, requested_through DATE,
            started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
            records_downloaded BIGINT NOT NULL DEFAULT 0 CHECK (records_downloaded >= 0),
            records_imported BIGINT NOT NULL DEFAULT 0 CHECK (records_imported >= 0),
            error_code VARCHAR(96), error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (requested_from IS NULL OR requested_through IS NULL OR requested_from <= requested_through)
        )
    """)
    op.execute("CREATE INDEX ix_feed_runs_feed_status ON ingestion.feed_runs(feed_key, status, created_at DESC)")
    op.execute("""
        CREATE TABLE ingestion.source_artifacts (
            artifact_id UUID PRIMARY KEY,
            run_id UUID REFERENCES ingestion.feed_runs(run_id) ON DELETE SET NULL,
            feed_key VARCHAR(48) NOT NULL, dataset_key VARCHAR(96) NOT NULL,
            session_date DATE, source_url TEXT NOT NULL, storage_uri TEXT NOT NULL,
            media_type VARCHAR(96), sha256 CHAR(64) NOT NULL,
            byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
            source_record_count BIGINT, imported_record_count BIGINT,
            parser_version VARCHAR(64) NOT NULL,
            validation_status VARCHAR(24) NOT NULL CHECK (validation_status IN ('pending','valid','invalid','quarantined')),
            downloaded_at TIMESTAMPTZ NOT NULL, imported_at TIMESTAMPTZ,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (feed_key, dataset_key, session_date, sha256)
        )
    """)
    op.execute("CREATE INDEX ix_source_artifacts_feed_date ON ingestion.source_artifacts(feed_key, dataset_key, session_date DESC)")
    op.execute("""
        CREATE TABLE ingestion.feed_checkpoints (
            feed_key VARCHAR(48) NOT NULL, dataset_key VARCHAR(96) NOT NULL,
            partition_key VARCHAR(160) NOT NULL, last_successful_date DATE,
            cursor_value TEXT,
            status VARCHAR(24) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','succeeded','failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (feed_key, dataset_key, partition_key)
        )
    """)
    op.execute("""
        CREATE TABLE ingestion.dataset_coverage (
            feed_key VARCHAR(48) NOT NULL, dataset_key VARCHAR(96) NOT NULL,
            coverage_from DATE, coverage_through DATE,
            expected_sessions INTEGER NOT NULL DEFAULT 0 CHECK (expected_sessions >= 0),
            loaded_sessions INTEGER NOT NULL DEFAULT 0 CHECK (loaded_sessions >= 0),
            status VARCHAR(24) NOT NULL DEFAULT 'not_started'
                CHECK (status IN ('not_started','loading','partial','ready','failed')),
            last_verified_at TIMESTAMPTZ, details JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (feed_key, dataset_key),
            CHECK (loaded_sessions <= expected_sessions OR expected_sessions = 0)
        )
    """)
    op.execute("""
        CREATE TABLE market_ref.instruments (
            market VARCHAR(24) NOT NULL, instrument_id VARCHAR(160) NOT NULL,
            exchange VARCHAR(24) NOT NULL, symbol VARCHAR(160) NOT NULL,
            asset_class VARCHAR(32) NOT NULL, instrument_type VARCHAR(48),
            currency CHAR(3), active_from DATE, active_through DATE,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (market, instrument_id),
            CHECK (active_from IS NULL OR active_through IS NULL OR active_from <= active_through)
        )
    """)
    op.execute("CREATE INDEX ix_market_ref_instruments_symbol ON market_ref.instruments(market, exchange, symbol)")
    op.execute("""
        CREATE TABLE market_ref.trading_sessions (
            market VARCHAR(24) NOT NULL, exchange VARCHAR(24) NOT NULL,
            segment VARCHAR(24) NOT NULL, session_date DATE NOT NULL,
            is_trading_day BOOLEAN NOT NULL, session_open TIME, session_close TIME,
            source_artifact_id UUID REFERENCES ingestion.source_artifacts(artifact_id),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (market, exchange, segment, session_date)
        )
    """)

    for schema in MARKET_SCHEMAS:
        op.execute(f'''
            CREATE TABLE "{schema}".daily_bars (
                trade_date DATE NOT NULL, instrument_id VARCHAR(160) NOT NULL,
                interval_code VARCHAR(16) NOT NULL DEFAULT '1D',
                open NUMERIC(24,8), high NUMERIC(24,8), low NUMERIC(24,8), close NUMERIC(24,8),
                volume NUMERIC(28,4), turnover NUMERIC(28,4),
                open_interest NUMERIC(28,4), oi_change NUMERIC(28,4), trades BIGINT,
                source_artifact_id UUID REFERENCES ingestion.source_artifacts(artifact_id),
                source_row_number BIGINT, imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, instrument_id, interval_code),
                CHECK (high IS NULL OR low IS NULL OR high >= low)
            )
        ''')
        op.execute(f'CREATE INDEX "ix_{schema}_daily_bars_instrument_date" ON "{schema}".daily_bars(instrument_id, trade_date DESC)')

    op.execute("""
        CREATE TABLE nse_fo.contract_master_snapshots (
            snapshot_id UUID PRIMARY KEY, effective_date DATE NOT NULL,
            source_url TEXT NOT NULL,
            source_artifact_id UUID REFERENCES ingestion.source_artifacts(artifact_id),
            sha256 CHAR(64) NOT NULL, parser_version VARCHAR(64) NOT NULL,
            row_count BIGINT NOT NULL CHECK (row_count >= 0),
            eligible_option_count BIGINT NOT NULL DEFAULT 0 CHECK (eligible_option_count >= 0),
            expiry_count INTEGER NOT NULL DEFAULT 0 CHECK (expiry_count >= 0),
            first_expiry DATE, last_expiry DATE,
            status VARCHAR(24) NOT NULL CHECK (status IN ('validating','valid','invalid','superseded')),
            imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            validation_details JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (effective_date, sha256),
            CHECK (first_expiry IS NULL OR last_expiry IS NULL OR first_expiry <= last_expiry)
        )
    """)
    op.execute("CREATE INDEX ix_nse_fo_contract_snapshots_effective ON nse_fo.contract_master_snapshots(effective_date DESC, status)")
    op.execute("""
        CREATE TABLE nse_fo.contracts (
            snapshot_id UUID NOT NULL REFERENCES nse_fo.contract_master_snapshots(snapshot_id) ON DELETE CASCADE,
            instrument_id VARCHAR(160) NOT NULL, symbol VARCHAR(160) NOT NULL,
            instrument_type VARCHAR(48) NOT NULL, expiry DATE, strike NUMERIC(24,8),
            option_type VARCHAR(2), lot_size INTEGER, tick_size NUMERIC(18,8),
            contract_start DATE, contract_end DATE, is_eligible BOOLEAN NOT NULL DEFAULT TRUE,
            raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (snapshot_id, instrument_id),
            CHECK (option_type IS NULL OR option_type IN ('CE','PE')),
            CHECK (lot_size IS NULL OR lot_size > 0),
            CHECK (tick_size IS NULL OR tick_size > 0)
        )
    """)
    op.execute("CREATE INDEX ix_nse_fo_contracts_lookup ON nse_fo.contracts(snapshot_id, symbol, expiry, option_type, strike)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS nse_fo.contracts")
    op.execute("DROP TABLE IF EXISTS nse_fo.contract_master_snapshots")
    for schema in MARKET_SCHEMAS:
        op.execute(f'DROP TABLE IF EXISTS "{schema}".daily_bars')
    op.execute("DROP TABLE IF EXISTS market_ref.trading_sessions")
    op.execute("DROP TABLE IF EXISTS market_ref.instruments")
    op.execute("DROP TABLE IF EXISTS ingestion.dataset_coverage")
    op.execute("DROP TABLE IF EXISTS ingestion.feed_checkpoints")
    op.execute("DROP TABLE IF EXISTS ingestion.source_artifacts")
    op.execute("DROP TABLE IF EXISTS ingestion.feed_runs")
