from app.air_qoc_store import AirQocStore


def _chain(premium, volume, oi, bid, ask):
    return {"oc": {"102": {"ce": {
        "security_id": "OPT-102-CE", "last_price": premium,
        "previous_close_price": 9.0, "volume": volume,
        "previous_volume": 800, "oi": oi, "previous_oi": 4500,
        "top_bid_price": bid, "top_bid_quantity": 100,
        "top_ask_price": ask, "top_ask_quantity": 120,
        "implied_volatility": 18.0,
    }}}}


def test_qualification_history_returns_distinct_same_contract_snapshots():
    store = AirQocStore(":memory:")
    try:
        for at, spot, premium, volume, oi in (
            ("2026-11-16T09:58:00+05:30", 100.0, 10.0, 1000, 5000),
            ("2026-11-16T09:59:30+05:30", 101.0, 11.0, 1500, 5500),
        ):
            store.save_option_chain(
                account_id="qoc-test", underlying_scrip="NIFTY",
                underlying_segment="IDX_I", expiry="2026-11-26",
                underlying_price=spot, observed_at=at,
                chain=_chain(premium, volume, oi, premium - 0.1, premium + 0.1),
            )
        rows = store.qualification_history(
            account_id="qoc-test", provider="dhan", underlying_scrip="NIFTY",
            expiry="2026-11-26", limit=100,
        )
        assert len(rows) == 2
        assert rows[0]["last_price"] == 11.0
        assert rows[1]["last_price"] == 10.0
    finally:
        store.close()
