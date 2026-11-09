from unittest.mock import patch

from app.market_data.nse_adapter import NSEBhavcopyMarketDataAdapter


def test_nse_option_master_search_uses_fo_store():
    adapter = NSEBhavcopyMarketDataAdapter()
    row = {
        "instrument_id": "NIFTY|2026-11-27|25000|CE",
        "symbol": "NIFTY",
        "expiry": "2026-11-27",
        "strike": 25000,
        "option_type": "CE",
        "lot_size": 65,
        "instrument_type": "OPTIDX",
    }
    with patch("app.market_data.nse_adapter.nse_data_rows", return_value=[row]) as query:
        instruments = __import__("asyncio").run(
            adapter.search_instruments("NIFTY", exchange_segment="NSE_FO")
        )
    query.assert_called_once_with("FO", symbol="NIFTY", limit=100)
    assert len(instruments) == 1
    assert instruments[0].option_type == "CE"
    assert instruments[0].strike == 25000


def test_nse_equity_master_search_uses_cm_store():
    adapter = NSEBhavcopyMarketDataAdapter()
    row = {"instrument_id": "SBIN", "symbol": "SBIN", "instrument_type": "EQ"}
    with patch("app.market_data.nse_adapter.nse_data_rows", return_value=[row]) as query:
        instruments = __import__("asyncio").run(
            adapter.search_instruments("SBIN", exchange_segment="NSE_CM")
        )
    query.assert_called_once_with("CM", symbol="SBIN", limit=100)
    assert len(instruments) == 1
    assert instruments[0].segment == "NSE_EQ"
