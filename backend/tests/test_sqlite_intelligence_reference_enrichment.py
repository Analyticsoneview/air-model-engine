import asyncio
import sqlite3

from app.market_data.service import MarketDataService


class EmptyRouter:
    def resolve(self, channel):
        return None


def test_hydrate_strategy_rows_uses_nse_sqlite_references(tmp_path, monkeypatch):
    bhavcopy = tmp_path / "nse_bhavcopy.sqlite3"
    universe = tmp_path / "nse_universe.sqlite3"

    with sqlite3.connect(bhavcopy) as db:
        db.execute("""
            CREATE TABLE nse_bhavcopy (
                market TEXT, trade_date TEXT, symbol TEXT, expiry TEXT,
                strike REAL, option_type TEXT, lot_size REAL
            )
        """)
        db.execute(
            "INSERT INTO nse_bhavcopy VALUES ('FO','2026-11-20','ABC','2026-12-31',100,'CE',125)"
        )
        db.execute(
            "INSERT INTO nse_bhavcopy VALUES ('FO','2026-11-21','ABC','2026-12-31',100,'CE',0)"
        )

    with sqlite3.connect(universe) as db:
        db.execute("""
            CREATE TABLE nse_index_constituent_snapshots (
                index_code TEXT, snapshot_date TEXT, symbol TEXT,
                company_name TEXT, industry TEXT, isin TEXT, source_url TEXT
            )
        """)
        db.execute("""
            INSERT INTO nse_index_constituent_snapshots
            VALUES ('NIFTY100','2026-11-20','ABC','ABC Industries Ltd',
                    'Chemicals','INE000A01000','https://nse.example/constituents.csv')
        """)

    monkeypatch.setenv("AIR_NSE_DB_PATH", str(bhavcopy))
    monkeypatch.setenv("AIR_NSE_UNIVERSE_DB_PATH", str(universe))

    service = MarketDataService(EmptyRouter(), None, None)
    rows = asyncio.run(service.hydrate_strategy_rows([{
        "signal_id": "abc-ce", "symbol": "ABC", "signal_date": "2026-11-21",
        "entry_date": "2026-11-21", "expiry": "2026-12-31",
        "strike": 100, "option_type": "CE", "lot_size": None,
        "sector": None, "evidence": {},
    }]))

    row = rows[0]
    assert row["lot_size"] == 125
    assert row["sector"] == "Chemicals"
    assert row["industry"] == "Chemicals"
    assert row["company_name"] == "ABC Industries Ltd"
    assert row["isin"] == "INE000A01000"
    assert row["evidence"]["nse_bhavcopy_reference"]["trade_date"] == "2026-11-20"
    assert row["evidence"]["nse_universe_reference"]["snapshot_date"] == "2026-11-20"


def test_hydrate_strategy_rows_preserves_existing_reference_values(tmp_path, monkeypatch):
    monkeypatch.setenv("AIR_NSE_DB_PATH", str(tmp_path / "missing-bhavcopy.sqlite3"))
    monkeypatch.setenv("AIR_NSE_UNIVERSE_DB_PATH", str(tmp_path / "missing-universe.sqlite3"))
    service = MarketDataService(EmptyRouter(), None, None)

    rows = asyncio.run(service.hydrate_strategy_rows([{
        "symbol": "ABC", "signal_date": "2026-11-21",
        "lot_size": 250, "sector": "Existing Sector",
        "industry": "Existing Industry", "company_name": "Existing Name",
        "evidence": {"keep": True},
    }]))

    assert rows[0]["lot_size"] == 250
    assert rows[0]["sector"] == "Existing Sector"
    assert rows[0]["industry"] == "Existing Industry"
    assert rows[0]["company_name"] == "Existing Name"
    assert rows[0]["evidence"] == {"keep": True}

def test_hydrate_historical_case_with_latest_available_constituent_snapshot(tmp_path, monkeypatch):
    universe = tmp_path / "nse_universe.sqlite3"
    with sqlite3.connect(universe) as db:
        db.execute("""
            CREATE TABLE nse_index_constituent_snapshots (
                index_code TEXT, snapshot_date TEXT, symbol TEXT,
                company_name TEXT, industry TEXT, isin TEXT, source_url TEXT
            )
        """)
        db.execute("""
            INSERT INTO nse_index_constituent_snapshots
            VALUES ('NIFTY100','2026-11-20','ABC','ABC Industries Ltd',
                    'Chemicals','INE000A01000','https://nse.example/constituents.csv')
        """)
    monkeypatch.setenv("AIR_NSE_UNIVERSE_DB_PATH", str(universe))
    monkeypatch.setenv("AIR_NSE_DB_PATH", str(tmp_path / "missing-bhavcopy.sqlite3"))

    service = MarketDataService(EmptyRouter(), None, None)
    # Mirrors the historical MASTER cohort: case rows are hydrated after
    # being appended, without requesting broker-history enrichment.
    rows = asyncio.run(service.hydrate_strategy_rows([{
        "signal_id": "historical-abc", "symbol": "ABC",
        "signal_date": "2026-10-12", "entry_date": "2026-10-12",
        "expiry": "2026-10-27", "strike": 100, "option_type": "CE",
        "entry_price": 10.0, "latest_price": 25.0, "pnl_pct": 150.0,
        "classification": "EXPIRED", "position_status": "EXPIRED",
        "evidence": {"source": "HISTORICAL_CASE", "keep": "yes"},
    }], max_contracts=0))

    row = rows[0]
    assert row["sector"] == "Chemicals"
    assert row["industry"] == "Chemicals"
    assert row["company_name"] == "ABC Industries Ltd"
    assert row["evidence"]["nse_universe_reference"]["snapshot_date"] == "2026-11-20"
    assert row["evidence"]["nse_universe_reference"]["as_of_date"] == "2026-10-12"
    assert row["evidence"]["nse_universe_reference"]["temporal_status"] == "LATEST_AVAILABLE_AFTER_AS_OF"
    assert row["evidence"]["source"] == "HISTORICAL_CASE"
    assert row["evidence"]["keep"] == "yes"
    assert row["entry_price"] == 10.0
    assert row["latest_price"] == 25.0
    assert row["pnl_pct"] == 150.0
    assert row["classification"] == "EXPIRED"
    assert row["position_status"] == "EXPIRED"

def test_lot_size_lookup_matches_exact_strike_beyond_first_hundred_rows(tmp_path, monkeypatch):
    bhavcopy = tmp_path / "nse_bhavcopy.sqlite3"
    with sqlite3.connect(bhavcopy) as db:
        db.execute("""
            CREATE TABLE nse_bhavcopy (
                market TEXT, trade_date TEXT, symbol TEXT, expiry TEXT,
                strike REAL, option_type TEXT, lot_size REAL
            )
        """)
        # More than 100 strikes precede the requested strike in the old
        # symbol-level LIMIT query. The exact-contract lookup must still find it.
        db.executemany(
            "INSERT INTO nse_bhavcopy VALUES ('FO','2026-10-26','ABC','2026-10-27',?,'CE',125)",
            [(float(strike),) for strike in range(100, 220)],
        )
    monkeypatch.setenv("AIR_NSE_DB_PATH", str(bhavcopy))
    monkeypatch.setenv("AIR_NSE_UNIVERSE_DB_PATH", str(tmp_path / "missing-universe.sqlite3"))

    service = MarketDataService(EmptyRouter(), None, None)
    rows = asyncio.run(service.hydrate_strategy_rows([{
        "signal_id": "abc-ce-219", "symbol": "ABC",
        "signal_date": "2026-10-12", "entry_date": "2026-10-12",
        "expiry": "2026-10-27", "strike": 219, "option_type": "CE",
        "lot_size": None, "evidence": {"preserve": True},
    }], max_contracts=0))

    assert rows[0]["lot_size"] == 125
    assert rows[0]["evidence"]["nse_bhavcopy_reference"]["trade_date"] == "2026-10-26"
    assert rows[0]["evidence"]["preserve"] is True
