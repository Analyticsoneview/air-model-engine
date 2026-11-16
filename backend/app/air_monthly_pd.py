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
