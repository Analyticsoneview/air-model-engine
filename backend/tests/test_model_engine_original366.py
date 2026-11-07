from app.model_engine_original366 import evaluate_original366_contract, evaluate_original366_rows


def bar(day, op, high, low, close, underlying_close=None):
    value = {"date": day, "open": op, "high": high, "low": low, "close": close, "quantity": 100}
    if underlying_close is not None:
        value["underlying_close"] = underlying_close
    return value


def sample_contract(instrument="STOCK", option_type="CE", entry_price=8.0, entry_date="2026-11-03",
                    expiry="2026-11-20", bars=None, sessions=13):
    return {
        "signal_id": "orig-1", "symbol": "TEST", "instrument_type": instrument,
        "option_type": option_type, "strike": 100, "expiry": expiry,
        "entry_date": entry_date, "entry_price": entry_price,
        "remaining_trading_sessions": sessions,
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
        bar("2026-11-20", 8.0, 9.0, 7.9, 8.5, underlying_close=115),
    ])
    item["position_quantity"] = 50
    item["evidence"]["charges_rupees"] = 10
    trade = evaluate_original366_contract(item, as_of="2026-11-20")["trades"][0]
    assert trade["classification"] == "EXPIRED_WIN"
    assert trade["expiry_intrinsic"] == 15
    assert trade["pnl_points"] == 7
    assert trade["gross_pnl_rupees"] == 350
    assert trade["net_pnl_rupees"] == 340


def test_original366_expiry_loss_and_missing_valuation_wait():
    loss = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.8, 8.2),
        bar("2026-11-20", 8.0, 8.5, 7.8, 8.1, underlying_close=100),
    ])
    assert evaluate_original366_contract(loss, as_of="2026-11-20")["status"] == "EXPIRED_LOSS"
    missing = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.8, 8.1),
        bar("2026-11-20", 8.0, 8.5, 7.8, 8.1),
    ])
    assert evaluate_original366_contract(missing, as_of="2026-11-20")["status"] == "WAIT"


def test_stock_premium_filter_and_index_exemption():
    bars = [bar("2026-11-03", 8, 8.5, 7.8, 8.2)]
    stock = sample_contract(entry_price=12, bars=bars)
    index = sample_contract(instrument="INDEX", entry_price=120, bars=bars)
    assert evaluate_original366_contract(stock, as_of="2026-11-03")["status"] == "REJECTED"
    assert evaluate_original366_contract(index, as_of="2026-11-03")["status"] == "HOLD"


def test_minimum_ten_verified_trading_sessions_is_required():
    enough = sample_contract(sessions=10, bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    too_few = sample_contract(sessions=9, bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    missing = sample_contract(sessions=None, bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    assert evaluate_original366_contract(enough, as_of="2026-11-03")["status"] == "HOLD"
    assert evaluate_original366_contract(too_few, as_of="2026-11-03")["status"] == "REJECTED"
    assert evaluate_original366_contract(missing, as_of="2026-11-03")["status"] == "REJECTED"


def test_original366_rows_require_explicit_membership_and_keep_missing_evidence_visible():
    tagged = sample_contract(bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    untagged = sample_contract(bars=[bar("2026-11-03", 8, 8.5, 7.8, 8.2)])
    untagged["evidence"] = {"daily_option_bars": tagged["evidence"]["daily_option_bars"]}
    no_bars = sample_contract(bars=[])
    result = evaluate_original366_rows([tagged, untagged, no_bars], as_of="2026-11-03")
    assert len(result) == 2
    assert result[1]["original366"]["status"] == "REJECTED" or result[1]["original366"]["status"] == "WAIT"


def test_original366_invalid_daily_bar_is_ignored():
    item = sample_contract(bars=[bar("2026-11-03", 8, 7, 6, 9)])
    result = evaluate_original366_contract(item, as_of="2026-11-03")
    assert result["data_quality"]["valid_bars"] == 0
    assert result["status"] == "WAIT"



def test_post_stop_close_above_original_entry_creates_watch_only_not_reentry():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.4, 7.6),  # original 5% SL
        bar("2026-11-04", 8.1, 8.8, 7.9, 8.2),  # closes above original 8.0 entry
    ])
    trade = evaluate_original366_contract(item, as_of="2026-11-04")["trades"][0]
    assert trade["classification"] == "SLHIT"
    assert trade["recovered_watch"]["trigger_date"] == "2026-11-04"
    assert trade["recovered_watch"]["trigger_close"] == 8.2
    assert trade["recovered_watch"]["watch_only"] is True
    assert trade["recovered_watch"]["is_reentry"] is False
    assert trade["recovered_watch"]["is_open_position"] is False


def test_post_stop_high_above_entry_without_close_does_not_create_recovered_watch():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.4, 7.6),
        bar("2026-11-04", 7.9, 8.8, 7.5, 7.95),
    ])
    trade = evaluate_original366_contract(item, as_of="2026-11-04")["trades"][0]
    assert trade["classification"] == "SLHIT"
    assert trade["recovered_watch"] is None



def test_recovered_uses_original_entry_with_ten_percent_stop_and_forty_five_target():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.5, 7.6),  # historical ORIGINAL366 5% SL
        bar("2026-11-04", 8.1, 8.8, 7.9, 8.2),  # RECOVERED signal
        bar("2026-11-05", 8.3, 11.8, 8.1, 11.2), # 45% target from original 8.0
    ])
    trade = evaluate_original366_contract(item, as_of="2026-11-05")["trades"][0]
    watch = trade["recovered_watch"]
    model = watch["exit_model"]
    assert trade["classification"] == "SLHIT"  # original 5% history is preserved
    assert watch["reference_entry_price"] == 8.0
    assert model["entry_price"] == 8.0
    assert model["stop_loss"] == 7.2
    assert model["target"] == 11.6
    assert model["outcome"] == "TARGET_FIRST"
    assert model["pnl_points"] == 3.6
    assert model["return_pct"] == 45.0


def test_recovered_ten_percent_stop_wins_when_hit_before_target():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.5, 7.6),
        bar("2026-11-04", 8.1, 8.8, 7.9, 8.2),
        bar("2026-11-05", 7.1, 8.9, 7.0, 7.4),
    ])
    trade = evaluate_original366_contract(item, as_of="2026-11-05")["trades"][0]
    model = trade["recovered_watch"]["exit_model"]
    assert model["outcome"] == "STOP_FIRST"
    assert model["exit_price"] == 7.2
    assert model["pnl_points"] == -0.8


def test_recovered_same_candle_target_and_stop_is_conservatively_stop_first():
    item = sample_contract(bars=[
        bar("2026-11-03", 8.0, 8.5, 7.5, 7.6),
        bar("2026-11-04", 8.1, 8.8, 7.9, 8.2),
        bar("2026-11-05", 8.0, 11.8, 7.0, 9.0),
    ])
    trade = evaluate_original366_contract(item, as_of="2026-11-05")["trades"][0]
    model = trade["recovered_watch"]["exit_model"]
    assert model["outcome"] == "STOP_FIRST"
    assert model["exit_reason"] == "SAME_CANDLE_STOP_FIRST"
    assert model["exit_price"] == 7.2
