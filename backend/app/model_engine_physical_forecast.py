"""Evidence-gated EXPIRY78 stock-option physical-delivery forecast.

This is a transparent, uncalibrated scenario estimate, not a guaranteed probability.
It requires verified underlying daily OHLCV. Missing source evidence is surfaced as
INSUFFICIENT_DATA; option premiums are never substituted for the underlying price.
"""
from __future__ import annotations

from datetime import date
from math import erf, sqrt
from statistics import mean, pstdev
from typing import Any

def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None

def _bars(evidence: dict[str, Any]) -> list[dict[str, float]]:
    raw = (evidence.get("daily_underlying_bars")
           or evidence.get("underlying_daily_bars")
           or evidence.get("stock_daily_bars")
           or evidence.get("underlying_ohlcv") or [])
    valid = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        close = _number(row.get("close") or row.get("c"))
        high = _number(row.get("high") or row.get("h"))
        low = _number(row.get("low") or row.get("l"))
        op = _number(row.get("open") or row.get("o"))
        volume = _number(row.get("volume") or row.get("quantity") or row.get("v"))
        if (close is None or high is None or low is None or op is None
                or min(close, high, low, op) <= 0 or high < max(op, close, low)
                or low > min(op, close) or (volume is not None and volume < 0)):
            continue
        valid.append({"date": str(row.get("date") or "")[:10], "open": op,
                      "high": high, "low": low, "close": close,
                      "volume": volume or 0.0})
    valid.sort(key=lambda x: x["date"])
    return valid

def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))

def forecast_physical_settlement(record: dict[str, Any], *, as_of: str | None = None) -> dict[str, Any]:
    """Forecast expiry ITM risk from stock OHLCV plus same-contract option evidence."""
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    kind = str(record.get("instrument_type") or "").upper()
    side = str(record.get("option_type") or "").upper()
    strike = _number(record.get("strike"))
    position = str(record.get("position_side") or "LONG_OPTION").upper()
    if kind in {"INDEX", "INDICES", "OPTIDX", "INDEX_OPTION"}:
        return {"physical_settlement_risk": "NOT_APPLICABLE", "forecast_itm": "NOT_APPLICABLE",
                "itm_probability_pct": None, "delivery_direction": "CASH_SETTLED_INDEX",
                "forecast_status": "INDEX_OPTION_EXCLUDED"}
    if side not in {"CE", "PE"} or strike is None or strike <= 0:
        return {"physical_settlement_risk": "UNKNOWN", "forecast_itm": "UNKNOWN",
                "itm_probability_pct": None, "delivery_direction": "UNKNOWN",
                "forecast_status": "INVALID_CONTRACT_METADATA"}
    bars = _bars(evidence)
    if len(bars) < 10:
        return {"physical_settlement_risk": "UNKNOWN", "forecast_itm": "UNKNOWN",
                "itm_probability_pct": None, "forecast_status": "INSUFFICIENT_UNDERLYING_OHLCV",
                "underlying_bars_used": len(bars), "delivery_direction_if_itm": _delivery(side, position)}
    try:
        cutoff = date.fromisoformat(str(as_of)[:10]) if as_of else date.fromisoformat(bars[-1]["date"])
        expiry = date.fromisoformat(str(record.get("expiry"))[:10])
    except (ValueError, TypeError):
        return {"physical_settlement_risk": "UNKNOWN", "forecast_itm": "UNKNOWN",
                "itm_probability_pct": None, "forecast_status": "INVALID_DATE"}
    bars = [b for b in bars if b["date"] and date.fromisoformat(b["date"]) <= cutoff]
    if len(bars) < 10:
        return {"physical_settlement_risk": "UNKNOWN", "forecast_itm": "UNKNOWN",
                "itm_probability_pct": None, "forecast_status": "INSUFFICIENT_AS_OF_HISTORY",
                "underlying_bars_used": len(bars), "delivery_direction_if_itm": _delivery(side, position)}
    closes = [b["close"] for b in bars]
    spot = closes[-1]
    returns = [(closes[i] / closes[i-1]) - 1.0 for i in range(1, len(closes)) if closes[i-1] > 0]
    recent = returns[-10:]
    if len(recent) < 5:
        return {"physical_settlement_risk": "UNKNOWN", "forecast_itm": "UNKNOWN",
                "itm_probability_pct": None, "forecast_status": "INSUFFICIENT_RETURN_HISTORY"}
    daily_drift = mean(recent)
    daily_vol = max(pstdev(returns[-20:]) if len(returns) >= 20 else pstdev(recent), 0.0005)
    tr = []
    for i, bar in enumerate(bars[-15:]):
        prev_close = bars[max(0, len(bars)-15+i-1)]["close"]
        tr.append(max(bar["high"]-bar["low"], abs(bar["high"]-prev_close), abs(bar["low"]-prev_close)))
    atr = mean(tr) if tr else spot * daily_vol
    calendar_dte = max(0, (expiry - cutoff).days)
    # Convert calendar days to an explicitly approximate number of trading sessions.
    sessions = max(0, round(calendar_dte * 5.0 / 7.0))
    projected = spot * ((1.0 + daily_drift) ** sessions)
    sigma = max(spot * daily_vol * sqrt(max(sessions, 1)), atr * sqrt(max(sessions, 1)) * 0.35)
    z = (projected - strike) / sigma if sigma > 0 else (float("inf") if projected > strike else float("-inf"))
    p_itm = (1.0 - _normal_cdf(-z)) if side == "CE" else _normal_cdf(-z)
    p_itm = min(1.0, max(0.0, p_itm))
    pct = round(p_itm * 100.0, 1)
    risk = "CRITICAL" if pct >= 75 else "HIGH" if pct >= 50 else "WATCH" if pct >= 25 else "LOW"
    forecast_itm = "YES" if pct >= 65 else "NO" if pct <= 35 else "UNCERTAIN"
    option_bars = evidence.get("daily_option_bars") or evidence.get("daily_bars") or []
    latest_option = option_bars[-1] if option_bars and isinstance(option_bars[-1], dict) else {}
    oi = _number(latest_option.get("open_interest") or latest_option.get("oi"))
    oi_change = _number(latest_option.get("oi_change"))
    option_volume = _number(latest_option.get("volume") or latest_option.get("quantity"))
    bid = _number(latest_option.get("bid_price") or latest_option.get("bid"))
    ask = _number(latest_option.get("ask_price") or latest_option.get("ask"))
    spread_pct = round((ask-bid)/((ask+bid)/2)*100, 2) if bid and ask and ask >= bid else None
    delivery = _delivery(side, position)
    quantity = _number(record.get("position_quantity") or record.get("quantity") or evidence.get("position_quantity"))
    quantity = int(quantity) if quantity is not None and quantity > 0 else None
    return {
        "physical_settlement_risk": risk,
        "forecast_itm": forecast_itm,
        "itm_probability_pct": pct,
        "forecast_stock_price": round(projected, 2),
        "forecast_range_low_1sd": round(max(0.01, projected-sigma), 2),
        "forecast_range_high_1sd": round(projected+sigma, 2),
        "current_underlying_price": round(spot, 2),
        "strike_distance_pct": round((spot-strike)/strike*100, 2),
        "atr_14_proxy": round(atr, 2),
        "days_to_expiry_calendar": calendar_dte,
        "estimated_trading_sessions": sessions,
        "delivery_direction_if_itm": delivery,
        "delivery_quantity_if_itm": quantity,
        "estimated_strike_notional_if_itm": round(strike*quantity, 2) if quantity else None,
        "option_open_interest": oi,
        "option_oi_change": oi_change,
        "option_volume": option_volume,
        "option_bid_ask_spread_pct": spread_pct,
        "option_confirmation": "AVAILABLE" if any(x is not None for x in (oi, oi_change, option_volume, spread_pct)) else "MISSING",
        "forecast_status": "MODEL_ESTIMATE_UNCALIBRATED",
        "underlying_bars_used": len(bars),
        "model_note": "Scenario estimate from recent underlying returns and ATR proxy; not historically calibrated and not a settlement guarantee.",
    }

def _delivery(option_type: str, position_side: str) -> str:
    if position_side not in {"LONG_OPTION", "SHORT_OPTION"}:
        return "UNKNOWN_POSITION_SIDE"
    takes = (option_type == "CE" and position_side == "LONG_OPTION") or (option_type == "PE" and position_side == "SHORT_OPTION")
    return "TAKE_SHARES" if takes else "GIVE_SHARES"
