from datetime import date, timedelta

from app.air_qoc_store import AirQocStore
from app.model_engine_expiryscan import scan_expiries


def test_expiryscan_latest_per_contract_and_survivor():
    store = AirQocStore(":memory:")
    expiry = (date.today() + timedelta(days=5)).isoformat()
    chain = {"oc": {"25000": {"ce": {
        "security_id": "123", "last_price": 20, "volume": 100,
        "oi": 300, "previous_oi": 250, "top_bid_price": 19.5,
        "top_ask_price": 20,
    }}}}
    store.save_option_chain(account_id="a", underlying_scrip=13,
                            underlying_segment="IDX_I", expiry=expiry,
                            underlying_price=25000, observed_at="2026-11-06T10:00:00+05:30",
                            chain=chain)
    chain["oc"]["25000"]["ce"]["volume"] = 200
    store.save_option_chain(account_id="a", underlying_scrip=13,
                            underlying_segment="IDX_I", expiry=expiry,
                            underlying_price=25000, observed_at="2026-11-06T15:45:00+05:30",
                            chain=chain)
    result = scan_expiries(store, account_id="a")
    assert result["total_contracts"] == 1
    row = result["rows"][0]
    assert row["survivor"] is True
    assert row["volume"] == 200
    assert row["scan_status"] == "LIQUIDITY_SCREEN_PASSED"
    assert row["qoc_score"] is None
    assert scan_expiries(store, account_id="other")["rows"] == []
    store.close()


def test_expiryscan_missing_quote_not_qualified():
    store = AirQocStore(":memory:")
    expiry = (date.today() + timedelta(days=12)).isoformat()
    store.save_option_chain(account_id="a", underlying_scrip=13,
                            underlying_segment="IDX_I", expiry=expiry,
                            underlying_price=None, observed_at="2026-11-06T15:45:00+05:30",
                            chain={"oc": {"25000": {"pe": {"volume": 100, "oi": 200}}}})
    row = scan_expiries(store, account_id="a")["rows"][0]
    assert row["survivor"] is False
    assert row["scan_status"] == "INSUFFICIENT_DATA"
    assert "bid_price" in row["missing_evidence"]
    store.close()
