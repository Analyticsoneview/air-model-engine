import sqlite3

from app.air_qoc_store import AirQocStore
from scripts.import_sqlite_domain_stores import run as import_domain_stores


def test_qoc_observations_import_to_postgres_and_remain_readable(tmp_path, monkeypatch):
    source = tmp_path / "air_qoc.sqlite3"
    monkeypatch.setenv("AIR_QOC_DB_PATH", str(source))
    db = sqlite3.connect(source)
    db.execute("""
        CREATE TABLE option_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
            account_id TEXT NOT NULL, underlying_scrip INTEGER NOT NULL,
            underlying_segment TEXT NOT NULL, expiry TEXT NOT NULL, underlying_price REAL,
            strike TEXT NOT NULL, option_type TEXT NOT NULL, security_id TEXT,
            last_price REAL, previous_close REAL, volume INTEGER, previous_volume INTEGER,
            open_interest INTEGER, previous_oi INTEGER, bid_price REAL, bid_quantity INTEGER,
            ask_price REAL, ask_quantity INTEGER, implied_volatility REAL, observed_at TEXT NOT NULL,
            UNIQUE(provider, account_id, underlying_scrip, expiry, strike, option_type, observed_at)
        )
    """)
    db.execute("""
        INSERT INTO option_observations (
            id,provider,account_id,underlying_scrip,underlying_segment,expiry,underlying_price,
            strike,option_type,security_id,last_price,previous_close,volume,previous_volume,
            open_interest,previous_oi,bid_price,bid_quantity,ask_price,ask_quantity,
            implied_volatility,observed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (7, "dhan", "test-account", 13, "IDX_I", "2026-12-31", 24500.0,
          "24500", "CE", "sec-1", 125.5, 120.0, 5000, 4000, 12000, 11000,
          125.0, 50, 126.0, 60, 18.2, "2026-11-11T10:00:00+05:30"))
    db.commit()
    db.close()

    result = import_domain_stores(tmp_path, dry_run=False)
    assert result["status"] == "IMPORTED_AND_RECONCILED"
    assert result["tables"]["option_observations"]["source_rows"] == 1

    store = AirQocStore()
    try:
        rows = store.latest_observations(account_id="test-account", provider="dhan", limit=5)
        assert len(rows) == 1
        assert rows[0]["id"] == 7
        assert rows[0]["last_price"] == 125.5
    finally:
        store.close()
