import sqlite3

from app.market_data.instrument_registry import MarketInstrumentDirectory
from scripts.import_sqlite_market_instruments import run as import_instruments


def test_market_instrument_master_import_and_snapshot_postgres(tmp_path, monkeypatch):
    source = tmp_path / "air_market_instruments.sqlite3"
    monkeypatch.setenv("AIR_MARKET_INSTRUMENT_DB_PATH", str(source))
    db = sqlite3.connect(source)
    db.executescript("""
        CREATE TABLE market_instruments (
            provider TEXT NOT NULL, account_id TEXT NOT NULL, exchange TEXT NOT NULL,
            symbol TEXT NOT NULL, underlying_symbol TEXT, token TEXT NOT NULL,
            segment TEXT NOT NULL, expiry TEXT, strike TEXT, option_type TEXT,
            lot_size INTEGER, instrument_type TEXT, tick_size TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, account_id, token)
        );
        CREATE TABLE market_master_refresh (
            provider TEXT NOT NULL, account_id TEXT NOT NULL,
            row_count INTEGER NOT NULL, source TEXT, refreshed_at TEXT NOT NULL,
            PRIMARY KEY(provider, account_id)
        );
    """)
    db.execute(
        "INSERT INTO market_instruments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("zerodha", "account-1", "NFO", "NIFTY26DEC24500CE", "NIFTY",
         "token-1", "NFO-OPT", "2026-12-31", "24500", "CE", 75,
         "OPTIDX", "0.05", "2026-11-11T10:00:00+00:00"),
    )
    db.execute(
        "INSERT INTO market_master_refresh VALUES(?,?,?,?,?)",
        ("zerodha", "account-1", 1, "official", "2026-11-11T10:00:00+00:00"),
    )
    db.commit()
    db.close()

    result = import_instruments(tmp_path, dry_run=False)
    assert result["status"] == "IMPORTED_AND_RECONCILED"
    assert result["market_instruments_source_rows"] == 1

    directory = MarketInstrumentDirectory()
    try:
        row = directory.get("zerodha", "account-1", "token-1")
        assert row["underlying_symbol"] == "NIFTY"
        assert row["lot_size"] == 75
        assert directory.master_status()[0]["row_count"] == 1
        assert directory.search("zerodha", "account-1", "NIFTY")[0]["token"] == "token-1"
        assert directory.replace_snapshot("zerodha", "account-1", [{
            "exchange": "NFO", "symbol": "NIFTY26DEC24500CE", "token": "token-2",
            "segment": "NFO-OPT", "underlying_symbol": "NIFTY", "expiry": "2026-12-31",
            "strike": "24500", "option_type": "CE", "lot_size": 75,
            "instrument_type": "OPTIDX", "tick_size": "0.05",
        }]) == 1
        assert directory.get("zerodha", "account-1", "token-1") is None
        assert directory.get("zerodha", "account-1", "token-2") is not None
    finally:
        directory.close()
