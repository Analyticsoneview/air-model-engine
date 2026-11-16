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
