"""Guard AIR's per-market PostgreSQL schema boundary and contract snapshot model."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

EXPECTED_MARKET_SCHEMAS = {"nse_cm", "nse_fo", "nse_com", "nse_cd", "us_market"}
EXPECTED_SHARED_SCHEMAS = {"market_ref", "ingestion", "research"}


def test_market_data_schema_migration_is_latest_linear_revision():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0030_market_data_schema_isolation"]
    revision = script.get_revision("0030_market_data_schema_isolation")
    assert revision.down_revision == "0029_customer_credentials"


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
