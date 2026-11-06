from app.model_engine_expiry78 import evaluate_expiry78_contract


def bar(day, op, high, low, close, quantity=100, underlying_close=None):
    item = {
        "date": day, "open": op, "high": high, "low": low,
        "close": close, "quantity": quantity,
    }
    if underlying_close is not None:
        item["underlying_close"] = underlying_close
    return item


def contract(instrument="STOCK", option_type="CE", strike=100, expiry="2026-11-10",
             bars=None, position_quantity=50):
    return {
        "symbol": "TEST", "instrument_type": instrument, "option_type": option_type,
        "strike": strike, "expiry": expiry, "position_quantity": position_quantity,
        "evidence": {"strategy_memberships": ["EXPIRY78"], "daily_option_bars": bars or []},
    }


def base_bars():
    return [
        bar("2026-11-03", 12, 13, 9, 10),      # prior bearish candle
        bar("2026-11-04", 9, 20, 8, 15),       # bullish body engulfs prior body; limit=8
        bar("2026-11-05", 9, 10, 7.8, 8.5),    # limit touch, no 5% stop
    ]


def test_stock_option_entry_limit_is_40_percent_of_engulfing_high_and_new_same_day():
    result = evaluate_expiry78_contract(contract(bars=base_bars()), as_of="2026-11-05")
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["entry_limit"] == 8.0
    assert trade["entry_price"] == 8.0
    assert trade["stop_loss"] == 7.6
    assert trade["classification"] == "NEW"
    assert trade["entry_day_quantity"] == 100
    assert trade["gross_pnl_rupees"] is None  # position size is deliberately not inferred


def test_open_trade_transitions_to_hold_after_entry_session():
    bars = base_bars() + [bar("2026-11-06", 8.5, 9, 8, 8.7)]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-06")
    assert result["trades"][0]["classification"] == "HOLD"


def test_same_day_low_breach_is_conservatively_counted_as_stop():
    bars = base_bars()[:2] + [bar("2026-11-05", 9, 10, 7.5, 8.5)]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-05")
    trade = result["trades"][0]
    assert trade["classification"] == "SL"
    assert trade["exit_reason"] == "SAME_DAY_STOP"
    assert trade["exit_price"] == 7.6


def test_gap_through_stop_exits_at_observed_open():
    bars = base_bars() + [bar("2026-11-06", 7.2, 8, 7, 7.5)]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-06")
    trade = result["trades"][0]
    assert trade["classification"] == "SL"
    assert trade["exit_reason"] == "GAP_THROUGH_STOP"
    assert trade["exit_price"] == 7.2


def test_only_unstopped_trade_with_expiry_intrinsic_is_survivor():
    bars = base_bars() + [
        bar("2026-11-10", 8.2, 12, 8.1, 10, underlying_close=110),
    ]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-10")
    trade = result["trades"][0]
    assert trade["classification"] == "EXPIRED"
    assert trade["expiry_survivor"] is True
    assert trade["intrinsic_value"] == 10
    assert trade["pnl_points"] == 2
    assert trade["gross_pnl_rupees"] == 100


def test_expiry_without_underlying_close_waits_for_verified_valuation():
    bars = base_bars() + [bar("2026-11-10", 8.2, 12, 8.1, 10)]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-10")
    assert result["trades"][0]["classification"] == "WAIT"
    assert result["trades"][0]["expiry_survivor"] is False


def test_stock_premium_cap_applies_but_index_options_are_exempt():
    stock_bars = [
        bar("2026-11-03", 20, 22, 18, 19),
        bar("2026-11-04", 18, 30, 17, 25),
        bar("2026-11-05", 13, 15, 11, 12),
    ]
    stock = evaluate_expiry78_contract(contract(bars=stock_bars), as_of="2026-11-05")
    index = evaluate_expiry78_contract(
        contract(instrument="INDEX", bars=stock_bars), as_of="2026-11-05"
    )
    assert stock["trade_count"] == 0
    assert index["trade_count"] == 1
    assert index["trades"][0]["entry_price"] == 12


def test_entry_day_quantity_below_ten_does_not_fill():
    bars = base_bars()[:2] + [bar("2026-11-05", 9, 10, 7.8, 8.5, quantity=9)]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-05")
    assert result["trade_count"] == 0
    assert result["status"] == "WAIT"


def test_invalid_ohlcv_is_excluded_and_expiry_day_entry_is_not_allowed():
    bars = [
        bar("2026-11-03", 12, 13, 9, 10),
        bar("2026-11-04", 9, 20, 8, 15),
        bar("2026-11-10", 9, 10, 7.8, 8.5),
        bar("2026-11-11", 9, 10, 8, 9),
    ]
    result = evaluate_expiry78_contract(contract(bars=bars), as_of="2026-11-10")
    assert result["trade_count"] == 0
    assert result["data_quality"]["valid_bars"] == 3


def test_missing_expiry_is_rejected():
    item = contract(bars=base_bars())
    item["expiry"] = None
    result = evaluate_expiry78_contract(item, as_of="2026-11-05")
    assert result["status"] == "REJECTED"


def test_expiry78_rows_require_explicit_membership_and_daily_bars():
    from app.model_engine_expiry78 import evaluate_expiry78_rows

    tagged = contract(bars=base_bars())
    tagged["signal_id"] = "tagged"
    untagged = contract(bars=base_bars())
    untagged["signal_id"] = "untagged"
    untagged["evidence"] = {"daily_option_bars": base_bars()}
    evaluated = evaluate_expiry78_rows([tagged, untagged], as_of="2026-11-05")
    assert [item["signal_id"] for item in evaluated] == ["tagged"]
    assert evaluated[0]["expiry78"]["trade_count"] == 1


def test_expiry78_strategy_tab_uses_engine_replay_results():
    from app.model_engine_strategies import build_strategy_views

    item = contract(bars=base_bars())
    item.update({
        "signal_id": "engine-entry",
        "classification": "WAIT",
        "signal_date": "2026-11-04",
        "entry_price": None,
        "entry_date": None,
        "days_to_expiry": 5,
    })
    views = build_strategy_views([item])
    assert views["EXPIRY78"]["audit"]["engine"] == "AIR_EXPIRY78_SEVEN_RULES"
    assert views["EXPIRY78"]["counts"]["NEW"] == 1
    assert views["EXPIRY78"]["counts"]["OPEN"] == 1
    assert views["EXPIRY78"]["groups"]["NEW"][0]["entry_price"] == 8.0


def test_dhan_optstk_instrument_type_obeys_stock_premium_cap():
    stock_bars = [
        bar("2026-11-03", 20, 22, 18, 19),
        bar("2026-11-04", 18, 30, 17, 25),
        bar("2026-11-05", 13, 15, 11, 12),
    ]
    item = contract(instrument="OPTSTK", bars=stock_bars)
    result = evaluate_expiry78_contract(item, as_of="2026-11-05")
    assert result["trade_count"] == 0
