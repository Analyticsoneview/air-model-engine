from datetime import date
from app.air_monthly_pd import monthly_reference_session, monthly_levels, evaluate_support_acceptance, expiry_tags, classify_expiry_participation, classify_price_structure

def test_reference_session_23rd_then_21st_then_previous():
    assert monthly_reference_session(2026,11,{"2026-11-23":"TRADING_DAY"}).day==23
    assert monthly_reference_session(2026,11,{"2026-11-21":"TRADING_DAY"}).day==21
    assert monthly_reference_session(2026,11,{"2026-11-20":"TRADING_DAY"}).day==20

def test_monthly_levels_use_supplied_completed_month():
    assert monthly_levels([{"low":100,"high":130},{"low":95,"high":125}])=={"pml":95.0,"pmh":130.0,"eq":112.5}

def test_support_two_sessions_and_intraday_breach():
    bars=[{"date":"2026-11-24","low":101},{"date":"2026-11-25","low":100}]
    assert evaluate_support_acceptance(bars,100)["status"]=="OPEN_FOR_BUY"
    bars[1]["low"]=99.99
    assert evaluate_support_acceptance(bars,100)["status"]=="INVALIDATED"
    assert evaluate_support_acceptance(bars[:1],100)["status"]=="WAITING"

def test_expiry_tags():
    assert expiry_tags(date(2026,11,26))["expiry_lead_days"]==4
    assert expiry_tags(date(2026,11,30))["expiry_tag"]=="EXPIRY_ON_MONTH_END"

def test_expiry_alone_does_not_mean_strong_participation():
    x=classify_expiry_participation(option_volume=100,historical_volume_avg=100,oi_change_pct=0,premium_change_pct=0,spread_pct=8,underlying_volume_ratio=1)
    assert x["classification"]=="WEAK_OR_UNCONFIRMED"

def test_pattern_requires_minimum_completed_history():
    bars=[{"date":str(i),"close":i+1,"low":i+1,"high":i+2} for i in range(8)]
    assert classify_price_structure(bars)["state"]=="INCOMPLETE"

def test_support_confirmation_ignores_reference_day_and_prior_bars():
    bars=[{"date":"2026-11-23","low":90},{"date":"2026-11-24","low":101},{"date":"2026-11-25","low":100}]
    result=evaluate_support_acceptance(bars,100,2,"2026-11-23")
    assert result["status"]=="OPEN_FOR_BUY"


def test_current_month_extremes_capture_discount_ml_and_premium_mh_without_future_bars():
    from app.air_monthly_pd import current_month_extremes
    bars = [
        {"date": "2026-11-03", "low": 105, "high": 145},
        {"date": "2026-11-18", "low": 90, "high": 155},
        {"date": "2026-11-24", "low": 80, "high": 170},  # must be excluded
    ]
    result = current_month_extremes(bars, reference_date="2026-11-21", pml=100, pmh=150)
    assert result["cml"] == 90 and result["cml_date"] == "2026-11-18"
    assert result["cmh"] == 155 and result["cmh_date"] == "2026-11-18"
    assert result["ml_candidate"] is True
    assert result["mh_candidate"] is True
    assert result["eq"] == 125


def test_current_month_extremes_do_not_qualify_inside_previous_month_range():
    from app.air_monthly_pd import current_month_extremes
    result = current_month_extremes(
        [{"date": "2026-11-20", "low": 110, "high": 140}],
        reference_date="2026-11-23", pml=100, pmh=150,
    )
    assert result["ml_candidate"] is False
    assert result["mh_candidate"] is False


def test_current_month_low_acceptance_requires_two_sessions_and_rejects_wick():
    from app.air_monthly_pd import evaluate_current_month_low_acceptance
    bars = [
        {"date": "2026-11-24", "low": 91},
        {"date": "2026-11-25", "low": 90},
    ]
    assert evaluate_current_month_low_acceptance(bars, 90, reference_date="2026-11-23")["status"] == "ML_CONFIRMED"
    bars[1]["low"] = 89.99
    assert evaluate_current_month_low_acceptance(bars, 90, reference_date="2026-11-23")["status"] == "INVALIDATED"


def test_current_month_high_rejection_requires_two_sessions():
    from app.air_monthly_pd import evaluate_resistance_rejection
    bars = [
        {"date": "2026-11-24", "high": 154, "close": 153},
        {"date": "2026-11-25", "high": 155, "close": 154},
    ]
    assert evaluate_resistance_rejection(bars, 155, reference_date="2026-11-23")["status"] == "REJECTION_CONFIRMED"
    bars[1]["high"] = 155.01
    assert evaluate_resistance_rejection(bars, 155, reference_date="2026-11-23")["status"] == "INVALIDATED"


def test_current_month_extremes_missing_data_fails_closed():
    from app.air_monthly_pd import current_month_extremes
    result = current_month_extremes([], reference_date="2026-11-23", pml=100, pmh=150)
    assert result["status"] == "DATA_INSUFFICIENT"



def test_pattern_lifecycle_marks_double_bottom_failed_on_completed_close_below_support():
    from app.air_monthly_pd import evaluate_pattern_lifecycle
    pattern = {"pattern": "W", "state": "CONFIRMED", "support_lows": [100, 101]}
    bars = [{"date": "2026-11-26", "close": 99, "low": 98, "high": 103}]
    result = evaluate_pattern_lifecycle(pattern, bars)
    assert result["state"] == "FAILED"
    assert result["failed_date"] == "2026-11-26"


def test_pattern_lifecycle_marks_double_top_failed_on_completed_close_above_resistance():
    from app.air_monthly_pd import evaluate_pattern_lifecycle
    pattern = {"pattern": "DOUBLE_TOP", "state": "FORMING", "resistance": [150, 151]}
    bars = [{"date": "2026-11-26", "close": 152, "low": 149, "high": 153}]
    assert evaluate_pattern_lifecycle(pattern, bars)["state"] == "FAILED"
