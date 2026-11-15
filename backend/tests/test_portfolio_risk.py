import json

from app.portfolio_risk import PortfolioRiskStore, build_portfolio_snapshot


def test_snapshot_normalizes_broker_rows_and_exposes_missing_capital():
    snapshot = build_portfolio_snapshot({
        "positions": [{"tradingSymbol": "ABC", "netQty": 10, "buyAvg": 100, "ltp": 110, "unrealizedProfit": 100}],
        "holdings": [{"tradingsymbol": "XYZ", "quantity": 5, "average_price": 200, "last_price": 220}],
    }, "dhan", "acct-1")
    assert snapshot["summary"]["position_count"] == 1
    assert snapshot["summary"]["holding_count"] == 1
    assert snapshot["summary"]["gross_market_value"] == 2200
    assert snapshot["summary"]["unrealized_pnl"] == 200
    assert snapshot["summary"]["return_pct_on_observed_invested_value"] == 9.52
    assert snapshot["summary"]["max_drawdown_pct"] is None
    assert snapshot["summary"]["drawdown_status"] == "INSUFFICIENT_EQUITY_HISTORY"
    assert "account_equity" in snapshot["summary"]["missing_fields"]


def test_short_position_net_exposure_is_negative_but_gross_is_positive():
    snapshot = build_portfolio_snapshot({
        "positions": [{"symbol": "BANK", "net_quantity": -2, "average_price": 100, "last_price": 90}],
        "holdings": [],
    }, "zerodha", "acct-2")
    assert snapshot["summary"]["gross_market_value"] == 180
    assert snapshot["summary"]["net_exposure"] == -180


def test_store_is_customer_isolated_and_keeps_snapshot_history():
    store = PortfolioRiskStore(":memory:")
    snapshot = build_portfolio_snapshot({
        "positions": [{"symbol": "ABC", "quantity": 1, "average_price": 10, "last_price": 12}],
        "holdings": [],
    }, "dhan", "acct-1")
    store.save("customer-a", snapshot)
    assert store.overview("customer-a")["account_count"] == 1
    assert store.overview("customer-b")["account_count"] == 0
    assert len(store.history("customer-a")) == 1
    store.close()


def test_no_fabricated_pnl_or_drawdown_when_broker_omits_fields():
    snapshot = build_portfolio_snapshot({"positions": [{"symbol": "ABC", "quantity": 2}], "holdings": []},
                                        "fyers", "acct-3")
    assert snapshot["summary"]["unrealized_pnl"] is None
    assert snapshot["summary"]["return_pct_on_observed_invested_value"] is None
    assert snapshot["summary"]["max_drawdown_pct"] is None
    assert snapshot["summary"]["data_quality"] == "PARTIAL"
