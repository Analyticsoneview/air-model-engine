from app.model_engine_original366 import evaluate_original366_contract, evaluate_original366_rows


def bar(day, op, high, low, close, underlying_close=None):
    value = {"date": day, "open": op, "high": high, "low": low, "close": close, "quantity": 100}
    if underlying_close is not None:
        value["underlying_close"] = underlying_close
    return value


def sample_contract(instrument="STOCK", option_type="CE", entry_price=8.0, entry_date="2026-11-03",
                    expiry="2026-11-06", bars=None):
    return {
        "signal_id": "orig-1", "symbol": "TEST", "instrument_type": instrument,
        "option_type": option_type, "strike": 100, "expiry": expiry,
        "entry_date": entry_date, "entry_price": entry_price,
        "evidence": {"strategy_memberships": ["ORIGINAL366"], "daily_option_bars": bars or []},
    }


def test_original366_applies_five_percent_stop_same_day():
    item = sample_contract(bars=[bar("2026-11-03", 8.0, 8.4, 7.5, 7.8)])
    result = evaluate_original366_contract(item, as_of="2026-11-03")
    trade = result["trades"][0]
    assert trade["classification"] == "SLHIT"
    assert trade["stop_loss"] == 7.6
    assert trade["exit_reason"] == "SAME_DAY_STOP"
    assert trade["exit_price"] == 7.6


def test_original366_gap_through_stop_exits_at_open():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.8, 8.2),
        bar("2026-11-04", 7.2, 7.8, 7.0, 7.4),
    ])
    trade = evaluate_original366_contract(item, as_of="2026-11-04")["trades"][0]
    assert trade["classification"] == "SLHIT"
    assert trade["exit_reason"] == "GAP_THROUGH_STOP"
    assert trade["exit_price"] == 7.2


def test_original366_holds_before_expiry_when_stop_not_hit():
    item = sample_contract(bars=[bar("2026-11-03", 8.0, 8.5, 7.8, 8.2)])
    trade = evaluate_original366_contract(item, as_of="2026-11-04")["trades"][0]
    assert trade["classification"] == "HOLD"


def test_original366_expiry_winner_uses_intrinsic_value():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.8, 8.2),
        bar("2026-11-06", 8.0, 9.0, 7.9, 8.5, underlying_close=115),
    ])
    item["position_quantity"] = 50
    item["evidence"]["charges_rupees"] = 10
    trade = evaluate_original366_contract(item, as_of="2026-11-06")["trades"][0]
    assert trade["classification"] == "EXPIRED_WIN"
    assert trade["expiry_intrinsic"] == 15
    assert trade["pnl_points"] == 7
    assert trade["gross_pnl_rupees"] == 350
    assert trade["net_pnl_rupees"] == 340


def test_original366_expiry_loss_and_missing_valuation_wait():
    loss = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.8, 8.2),
        bar("2026-11-06", 8.0, 8.5, 7.8, 8.1, underlying_close=100),
    ])
    assert evaluate_original366_contract(loss, as_of="2026-11-06")["status"] == "EXPIRED_LOSS"
    missing = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.8, 8.2),
        bar("2026-11-06", 8.0, 8.5, 7.8, 8.1),
    ])
    assert evaluate_original366_contract(missing, as_of="2026-11-06")["status"] == "WAIT"


def test_stock_premium_filter_and_index_exemption():
    bars = [bar("2026-11-03", 12, 13, 11, 12)]
    stock = sample_contract(entry_price=12, bars=bars)
    index = sample_contract(instrument="INDEX", entry_price=120, bars=bars)
    assert evaluate_original366_contract(stock, as_of="2026-11-03")["status"] == "REJECTED"
    assert evaluate_original366_contract(index, as_of="2026-11-03")["status"] == "HOLD"


def test_original366_rows_require_explicit_membership_and_daily_bars():
    tagged = sample_contract(bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    untagged = sample_contract(bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    untagged["evidence"] = {"daily_option_bars": tagged["evidence"]["daily_option_bars"]}
    assert len(evaluate_original366_rows([tagged, untagged], as_of="2026-11-03")) == 1


def test_original366_invalid_daily_bar_is_ignored():
    item = sample_contract(bars=[bar("2026-11-03", 8, 7, 6, 9)])
    result = evaluate_original366_contract(item, as_of="2026-11-03")
    assert result["data_quality"]["valid_bars"] == 0
    assert result["status"] == "WAIT"
