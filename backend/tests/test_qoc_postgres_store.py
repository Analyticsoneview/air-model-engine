import os
import pytest
import sqlite3

from app.air_qoc_store import AirQocStore
from scripts.import_sqlite_qoc import run as import_qoc_store


@pytest.mark.skipif(not os.getenv("AIR_DATABASE_URL"), reason="requires the disposable PostgreSQL integration workflow")
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

    result = import_qoc_store(tmp_path, dry_run=False)
    assert result["status"] == "IMPORTED_AND_RECONCILED"
    assert result["source_rows"] == 1
    assert result["target_rows_after"] == 1

    store = AirQocStore()
    try:
        rows = store.latest_observations(account_id="test-account", provider="dhan", limit=5)
        assert len(rows) == 1
        assert rows[0]["id"] == 7
        assert rows[0]["last_price"] == 125.5
        saved = store.save_option_chain(
            account_id="test-account", underlying_scrip=13,
            underlying_segment="IDX_I", expiry="2026-12-31",
            underlying_price=24501.0, observed_at="2026-11-11T10:00:00+05:30",
            provider="dhan",
            chain={"oc": {"24500": {"ce": {
                "security_id": "sec-1", "last_price": 126.0,
                "previous_close_price": 120.0, "volume": 5100,
                "previous_volume": 4000, "oi": 12100, "previous_oi": 11000,
                "top_bid_price": 125.5, "top_bid_quantity": 55,
                "top_ask_price": 126.5, "top_ask_quantity": 65,
                "implied_volatility": 18.3, "greeks": {},
            }}}},
        )
        assert saved == 1
        updated = store.latest_observations(account_id="test-account", provider="dhan", limit=5)
        assert len(updated) == 1
        assert updated[0]["last_price"] == 126.0
        assert updated[0]["volume"] == 5100
        store.save_option_chain(
            account_id="test-account", underlying_scrip=13,
            underlying_segment="IDX_I", expiry="2026-12-31",
            underlying_price=24505.0, observed_at="2026-11-11T10:02:00+05:30",
            provider="dhan",
            chain={"oc": {"24500": {"ce": {
                "security_id": "sec-1", "last_price": 127.0,
                "previous_close_price": 120.0, "volume": 5200,
                "previous_volume": 4000, "oi": 12200, "previous_oi": 11000,
                "top_bid_price": 126.5, "top_bid_quantity": 55,
                "top_ask_price": 127.5, "top_ask_quantity": 65,
                "implied_volatility": 18.4, "greeks": {},
            }}}},
        )
        history = store.qualification_history(
            account_id="test-account", provider="dhan",
            underlying_scrip="13", expiry="2026-12-31", limit=10,
        )
        assert len(history) == 2
        assert history[0]["last_price"] == 127.0
        # Non-Dhan adapters identify underlyings by symbol rather than numeric scrip ID.
        symbol_saved = store.save_option_chain(
            provider="zerodha", account_id="test-account",
            underlying_scrip="NIFTY", underlying_segment="NFO",
            expiry="2026-12-31", underlying_price=24510.0,
            observed_at="2026-11-11T10:01:00+05:30",
            chain={"oc": {"24500": {"pe": {
                "security_id": "sec-2", "last_price": 98.0,
                "volume": 200, "oi": 300, "greeks": {},
            }}}},
        )
        assert symbol_saved == 1
        symbol_rows = store.latest_observations(
            account_id="test-account", provider="zerodha", limit=5
        )
        assert symbol_rows[0]["underlying_scrip"] == "NIFTY"
    finally:
        store.close()
