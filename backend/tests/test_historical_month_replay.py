from app.historical_month_replay import replay_expiry78_month
from app.model_engine_expiry78 import evaluate_expiry78_contract


def _bars(expiry="2026-10-29"):
    return [
        {"trade_date": "2026-10-26", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": expiry, "strike": 100, "option_type": "CE",
         "open": 10, "high": 11, "low": 7, "close": 8, "volume": 100,
         "underlying_price": 105},
        {"trade_date": "2026-10-27", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": expiry, "strike": 100, "option_type": "CE",
         "open": 7, "high": 13, "low": 6, "close": 12, "volume": 100,
         "underlying_price": 106},
        {"trade_date": "2026-10-28", "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": expiry, "strike": 100, "option_type": "CE",
         "open": 5.5, "high": 6.0, "low": 5, "close": 5.8, "volume": 100,
         "underlying_price": 108},
        {"trade_date": expiry, "symbol": "AAA", "instrument_type": "OPTSTK",
         "expiry": expiry, "strike": 100, "option_type": "CE",
         "open": 6, "high": 7, "low": 5, "close": 6, "volume": 100,
         "underlying_price": 110},
    ]


def test_expiry_month_replay_finds_and_settles_expired_contract():
    report = replay_expiry78_month(_bars(), month="2026-10", as_of="2026-11-19")

    assert report["status"] == "COMPLETED"
    assert report["month_basis"] == "expiry"
    assert report["strategy_version"] == "EXPIRY78_DAILY_OHLCV_V2_UNRESOLVED_SAME_SESSION"
    assert report["contracts_examined"] == 1
    assert report["contracts_with_qualifying_entries"] == 1
    assert report["trade_count"] == 1
    trade = report["trades"][0]
    assert trade["signal_date"] == "2026-10-27"
    assert trade["entry_date"] == "2026-10-28"
    assert trade["classification"] == "EXPIRED"
    assert trade["position_status"] == "EXPIRY_SURVIVOR"
    assert trade["expiry_underlying_close"] == 110
    assert trade["latest_price"] == trade["intrinsic_value"] == 10
    assert trade["latest_price_date"] == "2026-10-29"
    assert trade["days_to_expiry"] == 1
    assert trade["current_pnl_points"] == trade["pnl_points"] == 4.8
    assert trade["current_pnl_rupees"] is None


def test_signal_month_includes_later_expiry_contracts():
    rows = _bars("2026-11-26")
    # Shift the signal/entry evidence into November, keeping the contract expiry
    # in a later month to verify that signal-month selection does not drop it.
    for row, day in zip(rows, ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-26"]):
        row["trade_date"] = day
        row["expiry"] = "2026-11-26"
    report = replay_expiry78_month(rows, month="2026-11", as_of="2026-11-26", basis="signal")
    assert report["month_basis"] == "signal"
    assert report["trade_count"] == 1
    trade = report["trades"][0]
    assert trade["signal_date"] == "2026-11-04"
    assert trade["expiry"] == "2026-11-26"
    assert trade["days_to_expiry"] == 21


def test_future_expiry_month_can_replay_contracts_from_current_data():
    rows = _bars("2026-12-31")[:3]
    report = replay_expiry78_month(rows, month="2026-12", as_of="2026-11-19", basis="expiry")
    assert report["month_basis"] == "expiry"
    assert report["contracts_examined"] == 1
    assert report["trade_count"] == 1
    trade = report["trades"][0]
    assert trade["signal_date"] == "2026-10-27"
    assert trade["expiry"] == "2026-12-31"
    assert trade["position_status"] == "OPEN"
    assert trade["days_to_expiry"] == 64


def test_expiry_month_does_not_include_other_expiry_months():
    rows = _bars() + [{
        **_bars()[-1], "expiry": "2026-11-26",
        "trade_date": "2026-11-19",
    }]
    report = replay_expiry78_month(rows, month="2026-10", as_of="2026-11-19")
    assert report["contracts_examined"] == 1
    assert report["trades"][0]["expiry"] == "2026-10-29"


def test_same_day_entry_and_stop_touch_is_unresolved_not_fabricated_sl():
    bars = [
        {"date": "2026-10-26", "open": 10, "high": 11, "low": 7, "close": 8, "quantity": 100},
        {"date": "2026-10-27", "open": 7, "high": 13, "low": 6, "close": 12, "quantity": 100},
        {"date": "2026-10-28", "open": 5.5, "high": 6.0, "low": 4.5, "close": 5.8, "quantity": 100},
    ]
    result = evaluate_expiry78_contract({
        "symbol": "AAA", "instrument_type": "OPTSTK", "option_type": "CE",
        "strike": 100, "expiry": "2026-10-29",
        "evidence": {"daily_option_bars": bars},
    }, as_of="2026-10-28")
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["classification"] == "UNRESOLVED"
    assert trade["position_status"] == "UNRESOLVED"
    assert trade["pnl_points"] is None


def test_month_replay_reports_empty_month_without_fabricating_signals():
    report = replay_expiry78_month([], month="2026-10", as_of="2026-11-19")
    assert report["contracts_examined"] == 0
    assert report["trade_count"] == 0
    assert report["trades"] == []



def test_october_trailing_reference_reconciliation_matches_saved_rows():
    import csv
    from pathlib import Path
    from app.historical_month_replay import _reconcile_october_2026_trailing_reference

    reference_path = Path(__file__).parents[1] / "app" / "reference_data" / "expiry78_45_trailing_backtest.csv"
    with reference_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reference = list(csv.DictReader(handle))
    trades = []
    for row in reference:
        reason = row["exit_reason"]
        if reason == "EXPIRY_INTRINSIC":
            reason = "EXPIRY_INTRINSIC_SETTLEMENT"
        trades.append({
            "symbol": row["underlying"], "option_type": row["type"],
            "strike": float(row["strike"]), "expiry": "2026-10-27",
            "entry_date": row["entry_date"], "entry_price": float(row["entry_price"]),
            "exit_date": row["exit_date"], "exit_price": float(row["exit_price"]),
            "exit_reason": reason,
        })
    result = _reconcile_october_2026_trailing_reference(trades)
    assert result["status"] == "MATCHED"
    assert result["reference_trade_count"] == 45
    assert result["matched_entry_count"] == 45
    assert result["exit_match_count"] == 45
    assert result["gross_pnl_match_count"] == 45


def test_october_trailing_reference_reports_row_level_mismatches():
    import csv
    from pathlib import Path
    from app.historical_month_replay import _reconcile_october_2026_trailing_reference

    reference_path = Path(__file__).parents[1] / "app" / "reference_data" / "expiry78_45_trailing_backtest.csv"
    with reference_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reference = list(csv.DictReader(handle))
    trades = []
    for row in reference:
        reason = "EXPIRY_INTRINSIC_SETTLEMENT" if row["exit_reason"] == "EXPIRY_INTRINSIC" else row["exit_reason"]
        trades.append({
            "symbol": row["underlying"], "option_type": row["type"],
            "strike": float(row["strike"]), "expiry": "2026-10-27",
            "entry_date": row["entry_date"], "entry_price": float(row["entry_price"]),
            "exit_date": row["exit_date"], "exit_price": float(row["exit_price"]),
            "exit_reason": reason,
        })
    trades[0]["exit_price"] += 1.0
    result = _reconcile_october_2026_trailing_reference(trades)
    assert result["status"] == "PARTIAL"
    assert result["matched_entry_count"] == 45
    assert result["exit_match_count"] == 44
    assert result["gross_pnl_match_count"] == 44
