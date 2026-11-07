from app.model_engine_pnl_calendar import build_pnl_calendar


def _trade(signal_id, strategy, entry_date, exit_date, entry, exit_price, quantity, pnl_points):
    return {
        "signal_id": signal_id, "strategy": strategy, "symbol": "TEST",
        "instrument_type": "STOCK", "option_type": "CE", "strike": 100,
        "expiry": "2026-12-31", "signal_date": entry_date,
        "entry_date": entry_date, "entry_price": entry, "position_quantity": quantity,
        "exit_date": exit_date, "exit_price": exit_price, "pnl_points": pnl_points,
        "classification": "TARGETS", "evidence": {},
    }


def test_calendar_separates_entry_capital_from_exit_realized_pnl_and_breaks_charges():
    trade = _trade("A", "EXPIRY78", "2026-11-02", "2026-11-04", 5, 7, 100, 2)
    result = build_pnl_calendar({"EXPIRY78": {"groups": {"TARGETS": [trade]} }}, year=2026, month=11)

    summary = result["summary"]["overall"]
    assert summary["capital_deployed"] == 500
    assert summary["gross_pnl"] == 200
    assert summary["estimated_or_actual_charges"] > 0
    assert summary["net_pnl"] == round(200 - summary["estimated_or_actual_charges"], 2)
    entry_day = next(row for row in result["days"] if row["date"] == "2026-11-02")
    exit_day = next(row for row in result["days"] if row["date"] == "2026-11-04")
    assert entry_day["capital_deployed"] == 500
    assert entry_day["gross_pnl"] == 0
    assert exit_day["gross_pnl"] == 200
    assert exit_day["trades"][0]["charges"]["components"]["brokerage"] == 40


def test_recovered_and_expiry78_are_reported_separately_and_physical_not_added():
    expiry_trade = _trade("A", "EXPIRY78", "2026-11-02", "2026-11-04", 5, 7, 100, 2)
    recovered_trade = _trade("B", "RECOVERED", "2026-11-03", "2026-11-05", 4, 6, 50, 2)
    result = build_pnl_calendar({
        "EXPIRY78": {"groups": {"TARGETS": [expiry_trade]}},
        "ORIGINAL366": {"groups": {"RECOVERED": [recovered_trade]}},
        "PHYSICAL_SETTLEMENT": {"rows": [{"source_gross_pnl": 999999}]},
    })
    assert result["summary"]["EXPIRY78"]["gross_pnl"] == 200
    assert result["summary"]["RECOVERED"]["gross_pnl"] == 100
    assert result["summary"]["overall"]["gross_pnl"] == 300
    assert result["summary"]["overall"]["capital_deployed"] == 700


def test_unknown_quantity_does_not_fabricate_rupee_pnl_or_capital():
    trade = _trade("A", "EXPIRY78", "2026-11-02", "2026-11-04", 5, 7, None, 2)
    result = build_pnl_calendar({"EXPIRY78": {"groups": {"TARGETS": [trade]}}})
    summary = result["summary"]["overall"]
    assert summary["capital_deployed"] == 0
    assert summary["gross_pnl"] == 0
    assert summary["capital_missing_quantity"] == 1


def test_expired_contracts_are_retained_in_calendar_and_trade_history_with_win_loss_outcomes():
    winner = _trade("EXP-WIN", "EXPIRY78", "2026-10-01", "2026-10-29", 5, 8, 100, 3)
    winner.update({
        "expiry": "2026-10-29", "classification": "EXPIRED",
        "exit_reason": "EXPIRY_INTRINSIC_SETTLEMENT",
    })
    loser = _trade("EXP-LOSS", "EXPIRY78", "2026-10-02", "2026-10-29", 5, 0, 100, -5)
    loser.update({
        "expiry": "2026-10-29", "classification": "EXPIRED",
        "exit_reason": "EXPIRY_INTRINSIC_SETTLEMENT",
    })
    breakeven = _trade("EXP-FLAT", "EXPIRY78", "2026-10-03", "2026-10-29", 5, 5, 100, 0)
    breakeven.update({
        "expiry": "2026-10-29", "classification": "EXPIRED",
        "exit_reason": "EXPIRY_INTRINSIC_SETTLEMENT",
    })

    result = build_pnl_calendar({
        "EXPIRY78": {"groups": {"EXPIRED": [winner, loser, breakeven]}}
    }, year=2026, month=10)

    assert result["expired_trade_summary"] == {
        "count": 3, "wins": 1, "losses": 1, "breakeven": 1, "pnl_pending": 0,
    }
    assert {trade["expiry_outcome"] for trade in result["expired_trades"]} == {
        "EXPIRED_WIN", "EXPIRED_LOSS", "EXPIRED_BREAKEVEN",
    }
    expiry_day = next(day for day in result["days"] if day["date"] == "2026-10-29")
    assert expiry_day["expired_contract_count"] == 3
    assert expiry_day["expired_wins"] == 1
    assert expiry_day["expired_losses"] == 1
    assert expiry_day["expired_breakeven"] == 1
    assert len(result["trades"]) == 3
