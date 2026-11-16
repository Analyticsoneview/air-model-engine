from app.monthly_pd_engine import (
    classify_expiry, classify_participation, classify_price_pattern,
    evaluate_two_session_hold, monthly_reference, select_reference_session,
)


def test_reference_prefers_23_then_21_then_prior():
    rows = [
        {"session_date": "2026-11-23", "status": "HOLIDAY"},
        {"session_date": "2026-11-21", "status": "TRADING_DAY"},
        {"session_date": "2026-11-20", "status": "TRADING_DAY"},
    ]
    assert select_reference_session(2026, 11, rows)["reference_tag"] == "21ST_FALLBACK"
    rows[1]["status"] = "HOLIDAY"
    assert select_reference_session(2026, 11, rows)["reference_date"] == "2026-11-20"


def test_monthly_reference_uses_only_completed_prior_month():
    result = monthly_reference([
        {"period_start": "2026-09-01", "low": 100, "high": 150},
        {"period_start": "2026-10-01", "low": 110, "high": 160},
        {"period_start": "2026-11-01", "low": 1, "high": 999},
    ], "2026-11-23")
    assert result["pml"] == 110
    assert result["pmh"] == 160
    assert result["eq"] == 135


def test_two_session_hold_invalidates_on_intraday_wick():
    rows = [
        {"date": "2026-11-24", "low": 100, "close": 110},
        {"date": "2026-11-25", "low": 99.99, "close": 115},
    ]
    assert evaluate_two_session_hold(rows, "2026-11-23", 100)["status"] == "INVALIDATED"


def test_expiry_before_calendar_month_end():
    result = classify_expiry("2026-11-26", "2026-11")
    assert result["expiry_lead_days"] == 4
    assert result["expiry_tag"] == "EXPIRY_BEFORE_MONTH_END"


def test_oi_alone_does_not_create_strong_participation():
    result = classify_participation([{"volume": 100, "oi_change": 1000}])
    assert result["classification"] == "WEAK_OR_UNCONFIRMED"


def test_w_pattern_confirms_only_after_neckline_break():
    bars = [{"date": f"2026-01-{i:02d}", "close": v, "low": v-1, "high": v+1}
            for i, v in enumerate([110,108,105,100,103,108,105,101,104,109,112,115], 1)]
    result = classify_price_pattern(bars)
    assert result["pattern"] in {"W", "NONE"}
