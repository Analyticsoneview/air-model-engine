"""Deterministic AIR MPDSM evaluators; caller supplies verified exchange sessions and bars."""
from calendar import monthrange
from datetime import date, timedelta
from statistics import mean
from typing import Any

def monthly_reference_session(year: int, month: int, sessions: dict[str, str]) -> date:
    twenty_third = date(year, month, 23)
    if sessions.get(twenty_third.isoformat()) == "TRADING_DAY":
        return twenty_third
    candidate = date(year, month, 21)
    if sessions.get(candidate.isoformat()) == "TRADING_DAY":
        return candidate
    while candidate.month == month:
        if sessions.get(candidate.isoformat()) == "TRADING_DAY":
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError("No prior NSE trading session in supplied calendar")

def monthly_levels(previous_month_bars: list[dict[str, Any]]) -> dict[str, float]:
    if not previous_month_bars:
        raise ValueError("Completed previous-month bars are required")
    lows=[float(x["low"]) for x in previous_month_bars]
    highs=[float(x["high"]) for x in previous_month_bars]
    if min(lows)<=0 or min(lows)>max(highs):
        raise ValueError("Invalid monthly OHLC range")
    pml,pmh=min(lows),max(highs)
    return {"pml":pml,"pmh":pmh,"eq":(pml+pmh)/2}

def evaluate_support_acceptance(bars: list[dict[str, Any]], pml: float, required_sessions: int=2, reference_date: str|None=None) -> dict[str, Any]:
    if required_sessions<1: raise ValueError("required_sessions must be positive")
    eligible=[row for row in bars if reference_date is None or str(row["date"])[:10] > str(reference_date)[:10]]
    observed=sorted(eligible,key=lambda x:str(x["date"]))[:required_sessions]
    if len(observed)<required_sessions:
        return {"status":"WAITING","sessions_observed":len(observed),"required_sessions":required_sessions,"breach_date":None}
    for row in observed:
        if float(row["low"])<float(pml):
            return {"status":"INVALIDATED","sessions_observed":len(observed),"required_sessions":required_sessions,"breach_date":str(row["date"])}
    return {"status":"OPEN_FOR_BUY","sessions_observed":len(observed),"required_sessions":required_sessions,"breach_date":None}

def expiry_tags(expiry_date: date) -> dict[str, Any]:
    month_end=date(expiry_date.year,expiry_date.month,monthrange(expiry_date.year,expiry_date.month)[1])
    lead=(month_end-expiry_date).days
    return {"expiry_date":expiry_date.isoformat(),"calendar_month_end":month_end.isoformat(),"expiry_lead_days":lead,
            "expiry_tag":"EXPIRY_BEFORE_MONTH_END" if lead>0 else "EXPIRY_ON_MONTH_END" if lead==0 else "EXPIRY_AFTER_MONTH_END"}

def classify_expiry_participation(*, option_volume: float|None, historical_volume_avg: float|None,
        oi_change_pct: float|None, premium_change_pct: float|None, spread_pct: float|None,
        underlying_volume_ratio: float|None) -> dict[str, Any]:
    checks={
      "volume_expansion":option_volume is not None and historical_volume_avg is not None and historical_volume_avg>0 and option_volume/historical_volume_avg>=1.5,
      "oi_confirmation":oi_change_pct is not None and abs(oi_change_pct)>=5,
      "premium_momentum":premium_change_pct is not None and abs(premium_change_pct)>=5,
      "liquid_spread":spread_pct is not None and 0<=spread_pct<=2,
      "underlying_volume":underlying_volume_ratio is not None and underlying_volume_ratio>=1.2}
    score=sum(checks.values())
    return {"classification":"STRONG_PARTICIPATION" if score>=4 else "MODERATE_PARTICIPATION" if score>=3 else "WEAK_OR_UNCONFIRMED",
            "evidence_score":score,"evidence":checks,
            "disclosure":"Expiry timing alone is not evidence of participation; require corroborating market evidence."}

def _pivots(rows, field, is_low, radius=2):
    found=[]
    for i in range(radius,len(rows)-radius):
        value=float(rows[i][field])
        others=[float(rows[j][field]) for j in range(i-radius,i+radius+1) if j!=i]
        if value<=min(others) if is_low else value>=max(others):
            found.append((i,value))
    return found

def classify_price_structure(bars: list[dict[str, Any]], tolerance_pct: float=2.5) -> dict[str, Any]:
    rows=sorted(bars,key=lambda x:str(x["date"]))
    if len(rows)<12: return {"pattern":"NONE","state":"INCOMPLETE","confidence":0,"reason":"At least 12 completed bars required"}
    closes=[float(x["close"]) for x in rows]
    lows=_pivots(rows,"low",True); highs=_pivots(rows,"high",False)
    if len(lows)>=2:
        (i1,l1),(i2,l2)=lows[-2:]
        if i2-i1>=4 and abs(l1-l2)/max(l1,l2)*100<=tolerance_pct:
            neckline=max(float(x["high"]) for x in rows[i1:i2+1])
            confirmed=closes[-1]>neckline
            return {"pattern":"W","state":"CONFIRMED" if confirmed else "FORMING","confidence":85 if confirmed else 65,
                    "neckline":neckline,"support_lows":[l1,l2],
                    "reason":"Two comparable pivot lows and neckline close" if confirmed else "Double-bottom candidate; neckline not broken"}
    if len(highs)>=2:
        (i1,h1),(i2,h2)=highs[-2:]
        if i2-i1>=4 and abs(h1-h2)/max(h1,h2)*100<=tolerance_pct:
            return {"pattern":"DOUBLE_TOP","state":"FORMING","confidence":60,"resistance":[h1,h2],"reason":"Comparable swing highs; monitor support"}
    n=len(closes); a=mean(closes[:n//3]); b=mean(closes[n//3:2*n//3]); c=mean(closes[2*n//3:])
    if a>b and c>a and (c-b)/b>=.08:
        return {"pattern":"V","state":"FORMING","confidence":65,"reason":"Sharp recovery candidate; needs follow-through"}
    if a>b and c>b and (c-b)/b>=.04:
        return {"pattern":"U","state":"FORMING","confidence":60,"reason":"Rounded recovery candidate; needs higher low and resistance break"}
    if a<b and c>b and (c-b)/b>=.04:
        return {"pattern":"N","state":"FORMING","confidence":60,"reason":"Rally-pullback-renewed-rise candidate"}
    return {"pattern":"NONE","state":"INCOMPLETE","confidence":0,"reason":"No defined pattern met conservative rules"}

def classify_premium_discount(close: float, pml: float, pmh: float) -> str:
    if float(pmh) <= float(pml):
        raise ValueError("PMH must be greater than PML")
    eq=(float(pml)+float(pmh))/2.0
    if close < pml: return "BELOW_PML"
    if close <= eq: return "DISCOUNT"
    if close < pmh: return "PREMIUM"
    return "AT_OR_ABOVE_PMH"


def current_month_extremes(
    current_month_bars: list[dict[str, Any]],
    *,
    reference_date: str,
    pml: float,
    pmh: float,
) -> dict[str, Any]:
    """Freeze current-month low/high using completed bars through the reference session."""
    if float(pmh) <= float(pml):
        raise ValueError("PMH must be greater than PML")
    cutoff = str(reference_date)[:10]
    rows = [
        row for row in current_month_bars
        if str(row.get("date", ""))[:7] == cutoff[:7]
        and str(row.get("date", ""))[:10] <= cutoff
    ]
    rows = sorted(rows, key=lambda row: str(row["date"]))
    if not rows or any("low" not in row or "high" not in row for row in rows):
        return {
            "status": "DATA_INSUFFICIENT", "reference_date": cutoff,
            "cml": None, "cml_date": None, "cmh": None, "cmh_date": None,
            "ml_candidate": False, "mh_candidate": False,
        }
    lows = [(float(row["low"]), str(row["date"])[:10]) for row in rows]
    highs = [(float(row["high"]), str(row["date"])[:10]) for row in rows]
    if any(low <= 0 for low, _ in lows) or any(high <= 0 for high, _ in highs):
        raise ValueError("Current-month OHLC values must be positive")
    cml, cml_date = min(lows, key=lambda item: item[0])
    cmh, cmh_date = max(highs, key=lambda item: item[0])
    eq = (float(pml) + float(pmh)) / 2.0
    discount_zone = cml <= eq
    premium_zone = cmh >= eq
    ml_candidate = cml < float(pml) and discount_zone
    mh_candidate = cmh > float(pmh) and premium_zone
    return {
        "status": "REFERENCE_CAPTURED", "reference_date": cutoff,
        "pml": float(pml), "pmh": float(pmh), "eq": eq,
        "cml": cml, "cml_date": cml_date, "cml_zone": "DISCOUNT" if discount_zone else "PREMIUM",
        "cmh": cmh, "cmh_date": cmh_date, "cmh_zone": "PREMIUM" if premium_zone else "DISCOUNT",
        "ml_candidate": ml_candidate, "ml_status": "CANDIDATE" if ml_candidate else "NOT_QUALIFIED",
        "mh_candidate": mh_candidate, "mh_status": "CANDIDATE" if mh_candidate else "NOT_QUALIFIED",
        "disclosure": "Current-month extremes are reference candidates, not automatic reversal signals.",
    }


def evaluate_resistance_rejection(
    bars: list[dict[str, Any]], cmh: float, required_sessions: int = 2,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Confirm rejection only when subsequent completed sessions fail to exceed CMH and close below it."""
    if required_sessions < 1:
        raise ValueError("required_sessions must be positive")
    eligible = [row for row in bars if reference_date is None or str(row["date"])[:10] > str(reference_date)[:10]]
    observed = sorted(eligible, key=lambda row: str(row["date"]))[:required_sessions]
    if len(observed) < required_sessions:
        return {"status": "WAITING", "sessions_observed": len(observed), "required_sessions": required_sessions, "breach_date": None}
    for row in observed:
        if float(row["high"]) > float(cmh) or float(row["close"]) >= float(cmh):
            return {"status": "INVALIDATED", "sessions_observed": len(observed), "required_sessions": required_sessions, "breach_date": str(row["date"])}
    return {"status": "REJECTION_CONFIRMED", "sessions_observed": len(observed), "required_sessions": required_sessions, "breach_date": None}


def evaluate_current_month_low_acceptance(
    bars: list[dict[str, Any]], cml: float, required_sessions: int = 2,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Require two subsequent completed sessions without an intraday wick below the candidate CML."""
    result = evaluate_support_acceptance(bars, cml, required_sessions, reference_date)
    if result["status"] == "OPEN_FOR_BUY":
        result["status"] = "ML_CONFIRMED"
    return result
