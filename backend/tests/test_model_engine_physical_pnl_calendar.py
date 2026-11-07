from app.model_engine_pnl_calendar import build_pnl_calendar


def test_physical_settlement_is_visible_but_excluded_from_combined_strategy_pnl():
    result = build_pnl_calendar(
        {},
        physical_review={"rows": [{
            "symbol": "ABC", "option_type": "CE", "strike": 100,
            "expiry": "2026-10-27", "entry_premium": 2.0,
            "quantity_shares": 500, "source_gross_pnl": 250.0,
            "source_recorded_expiry_value": 2.5,
            "settlement_status": "PROVISIONAL_NOT_CONFIRMED",
            "itm_status": "PENDING_UNDERLYING_CLOSE",
        }]},
    )
    physical = result["summary"]["PHYSICAL_SETTLEMENT"]
    assert physical["contract_count"] == 1
    assert physical["capital_deployed"] == 1000
    assert physical["gross_pnl"] == 250
    assert physical["charges"] is None
    assert physical["net_pnl"] is None
    assert result["summary"]["overall"]["gross_pnl"] == 0
    day = next(row for row in result["days"] if row["date"] == "2026-10-27")
    assert day["physical_settlement_gross_pnl"] == 250
    assert day["trades"][0]["strategy"] == "PHYSICAL_SETTLEMENT"
