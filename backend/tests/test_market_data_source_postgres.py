import sqlite3

from app.market_data.provider_registry import MarketDataSourceRegistry
from scripts.import_sqlite_market_data_sources import run as import_sources


def test_market_data_source_and_failover_import_postgres(tmp_path, monkeypatch):
    source = tmp_path / "air_market_sources.sqlite3"
    monkeypatch.setenv("AIR_MARKET_SOURCE_DB_PATH", str(source))
    db = sqlite3.connect(source)
    db.executescript("""
        CREATE TABLE market_data_sources (
            channel TEXT PRIMARY KEY, provider TEXT NOT NULL, account_id TEXT,
            enabled INTEGER NOT NULL DEFAULT 0, fallback_provider TEXT,
            fallback_account_id TEXT, failover_enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE market_data_failover (
            channel TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            candidates_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
        );
    """)
    db.execute(
        "INSERT INTO market_data_sources VALUES(?,?,?,?,?,?,?,?)",
        ("historical", "dhan", "account-1", 1, None, None, 0, "2026-11-11T10:00:00+00:00"),
    )
    db.execute(
        "INSERT INTO market_data_failover VALUES(?,?,?,?)",
        ("historical", 1, '[{"provider":"zerodha","account_id":"account-2"}]',
         "2026-11-11T10:00:00+00:00"),
    )
    db.commit()
    db.close()

    result = import_sources(tmp_path, dry_run=False)
    assert result["status"] == "IMPORTED_AND_RECONCILED"

    registry = MarketDataSourceRegistry()
    try:
        assert registry.selections()["historical"]["provider"] == "dhan"
        failover = registry.failover()["historical"]
        assert failover["enabled"] is True
        assert failover["candidates"][0]["provider"] == "zerodha"
        registry.set_source("live", "dhan", "account-1", True)
        assert registry.selections()["live"]["enabled"] is True
        registry.set_failover("live", [{"provider": "fyers", "account_id": "account-3"}], True)
        assert registry.failover()["live"]["candidates"][0]["provider"] == "fyers"
    finally:
        registry.close()
