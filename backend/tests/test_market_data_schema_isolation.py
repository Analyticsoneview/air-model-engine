"""Guard AIR's per-market PostgreSQL schema boundary and contract snapshot model."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

EXPECTED_MARKET_SCHEMAS = {"nse_cm", "nse_fo", "nse_com", "nse_cd", "us_market"}
EXPECTED_SHARED_SCHEMAS = {"market_ref", "ingestion", "research"}


def test_market_data_schema_migration_is_latest_linear_revision():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0035_equity_sector_levels"]
    revision = script.get_revision("0035_equity_sector_levels")
    assert revision.down_revision == "0034_market_reference_history"
    assert len(revision.revision) <= 32


def test_market_data_schemas_are_isolated_and_have_shared_ingestion_ledger():
    migration = Path("migrations/versions/0030_market_data_schema_isolation.py").read_text()
    for schema in EXPECTED_MARKET_SCHEMAS | EXPECTED_SHARED_SCHEMAS:
        assert f'"{schema}"' in migration
    for table in (
        "ingestion.feed_runs", "ingestion.source_artifacts",
        "ingestion.feed_checkpoints", "ingestion.dataset_coverage",
        "market_ref.instruments", "market_ref.trading_sessions",
        "nse_fo.contract_master_snapshots", "nse_fo.contracts",
    ):
        assert table in migration
    assert "UNIQUE (effective_date, sha256)" in migration
    assert "PRIMARY KEY (snapshot_id, instrument_id)" in migration
    assert "source_artifact_id UUID REFERENCES ingestion.source_artifacts" in migration
    downgrade = migration.split("def downgrade() -> None:", 1)[1]
    assert "DROP SCHEMA" not in downgrade

import os
import pytest
from sqlalchemy import create_engine, text


@pytest.mark.skipif(not os.getenv("AIR_DATABASE_URL"), reason="requires disposable PostgreSQL with migrations applied")
def test_market_data_postgres_schemas_and_tables_exist():
    engine = create_engine(os.environ["AIR_DATABASE_URL"])
    expected = EXPECTED_MARKET_SCHEMAS | EXPECTED_SHARED_SCHEMAS
    try:
        with engine.connect() as connection:
            schemas = set(connection.execute(text(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(:names)"
            ), {"names": list(expected)}).scalars())
            assert schemas == expected

            tables = set(connection.execute(text("""
                SELECT table_schema || '.' || table_name
                FROM information_schema.tables
                WHERE table_schema = ANY(:names) AND table_type = 'BASE TABLE'
            """), {"names": list(expected)}).scalars())

            for schema in EXPECTED_MARKET_SCHEMAS:
                assert f"{schema}.daily_bars" in tables
            assert {
                "ingestion.feed_runs", "ingestion.source_artifacts",
                "ingestion.feed_checkpoints", "ingestion.dataset_coverage",
                "market_ref.instruments", "market_ref.trading_sessions",
                "nse_fo.contract_master_snapshots", "nse_fo.contracts",
            }.issubset(tables)
    finally:
        engine.dispose()
