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
