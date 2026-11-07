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
