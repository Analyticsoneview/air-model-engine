"""AIR MPDSM: deterministic monthly reference, expiry and price-pattern evaluators.

This module is provider-independent. It consumes normalized OHLCV/derivative rows and
never fetches data, places orders, or treats missing data as a positive signal.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any, Iterable

VALID_CALENDAR_STATES = {"TRADING_DAY", "SPECIAL_SESSION"}
PATTERNS = {"U", "V", "N", "W"}


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def select_reference_session(year: int, month: int, exchange_sessions: Iterable[dict]) -> dict:
    """Select 23rd; if unavailable try 21st; otherwise previous confirmed session."""
    by_date = {_day(row["session_date"]): row for row in exchange_sessions}
    twenty_third = date(year, month, 23)
    twenty_first = date(year, month, 21)
    for candidate, tag in ((twenty_third, "23RD"), (twenty_first, "21ST_FALLBACK")):
        row = by_date.get(candidate)
        if row and str(row.get("status", "")).upper() in VALID_CALENDAR_STATES:
            return {"reference_date": candidate.isoformat(), "reference_tag": tag,
                    "calendar_source": row.get("source", "EXCHANGE_CALENDAR")}
    prior = [d for d, row in by_date.items()
             if d < twenty_first and str(row.get("status", "")).upper() in VALID_CALENDAR_STATES]
    if not prior:
        return {"reference_date": None, "reference_tag": "DATA_INSUFFICIENT",
                "calendar_source": None}
    chosen = max(prior)
    return {"reference_date": chosen.isoformat(), "reference_tag": "PREVIOUS_SESSION_FALLBACK",
            "calendar_source": by_date[chosen].get("source", "EXCHANGE_CALENDAR")}


def monthly_reference(monthly_bars: Iterable[dict], reference_date: str) -> dict:
    """Use only a fully completed month strictly before the reference session."""
    ref = _day(reference_date)
    completed = []
    for bar in monthly_bars:
        start = _day(bar.get("period_start") or bar.get("date") or bar.get("start_time"))
        if (start.year, start.month) < (ref.year, ref.month):
            completed.append((start, bar))
    if not completed:
        return {"status": "DATA_INSUFFICIENT", "reason": "No completed prior-month OHLC bar"}
    start, bar = max(completed, key=lambda item: item[0])
    low, high = float(bar["low"]), float(bar["high"])
    if low <= 0 or high < low:
        return {"status": "DATA_INSUFFICIENT", "reason": "Invalid prior-month range"}
    return {"status": "REFERENCE_CAPTURED", "reference_date": ref.isoformat(),
            "reference_month": f"{ref.year:04d}-{ref.month:02d}",
            "source_month": f"{start.year:04d}-{start.month:02d}",
            "pml": low, "pmh": high, "eq": (low + high) / 2,
            "tags": ["23RD_REFERENCE", "23RD_FORECAST", "HISTORICAL"]}


def evaluate_two_session_hold(daily_bars: Iterable[dict], reference_date: str, pml: float) -> dict:
    """Require two subsequent complete sessions with no intraday low below PML."""
    ref = _day(reference_date)
    rows = sorted(((_day(row.get("date") or row.get("start_time")), row)
                   for row in daily_bars if _day(row.get("date") or row.get("start_time")) > ref),
                  key=lambda item: item[0])
    if len(rows) < 2:
        return {"status": "WAITING_FOR_CONFIRMATION",
                "completed_sessions": len(rows), "required_sessions": 2}
    first_two = rows[:2]
    breached = [d.isoformat() for d, row in first_two if float(row["low"]) < float(pml)]
    if breached:
        return {"status": "INVALIDATED", "breach_dates": breached,
                "completed_sessions": 2, "rule": "Any intraday low below PML invalidates"}
    return {"status": "OPEN_FOR_BUY", "completed_sessions": 2,
            "confirmation_dates": [d.isoformat() for d, _ in first_two],
            "rule": "Two complete sessions held above PML; watchlist qualification only"}


def classify_premium_discount(close: float, pml: float, pmh: float) -> str:
    eq = (float(pml) + float(pmh)) / 2
    if close < pml:
        return "BELOW_PML"
    if close <= eq:
        return "DISCOUNT"
    if close < pmh:
        return "PREMIUM"
    return "AT_OR_ABOVE_PMH"


def classify_expiry(expiry_date: str, calendar_month: str) -> dict:
    expiry = _day(expiry_date)
    year, month = (int(x) for x in calendar_month.split("-"))
    month_end = date(year, month, monthrange(year, month)[1])
    lead = (month_end - expiry).days
    return {"expiry_date": expiry.isoformat(),
            "calendar_month_end": month_end.isoformat(),
            "expiry_lead_days": lead,
            "expiry_tag": "EXPIRY_BEFORE_MONTH_END" if lead > 0 else
                          "EXPIRY_ON_MONTH_END" if lead == 0 else "EXPIRY_AFTER_MONTH_END"}


def classify_participation(option_rows: Iterable[dict], historical_volume_avg: float | None = None) -> dict:
    """Classify only with corroborating derivative evidence; OI alone is insufficient."""
    rows = list(option_rows)
    if not rows:
        return {"classification": "DATA_INSUFFICIENT", "evidence": []}
    volume = sum(float(r.get("volume") or 0) for r in rows)
    oi_change = sum(float(r.get("oi_change") or 0) for r in rows)
    spread_values = []
    for row in rows:
        bid, ask = row.get("bid"), row.get("ask")
        if bid is not None and ask is not None and float(bid) > 0:
            spread_values.append((float(ask) - float(bid)) / float(bid) * 100)
    volume_ratio = (volume / historical_volume_avg) if historical_volume_avg and historical_volume_avg > 0 else None
    evidence = {
        "volume": volume, "oi_change": oi_change,
        "volume_vs_average": volume_ratio,
        "average_bid_ask_spread_pct": mean(spread_values) if spread_values else None,
        "contracts_observed": len(rows),
    }
    corroboration = sum((
        volume_ratio is not None and volume_ratio >= 1.5,
        oi_change > 0,
        bool(spread_values) and mean(spread_values) <= 3.0,
        any(float(r.get("premium_change_pct") or 0) > 0 for r in rows),
    ))
    classification = "STRONG" if corroboration >= 3 else "MODERATE" if corroboration == 2 else "WEAK_OR_UNCONFIRMED"
    return {"classification": classification, "evidence": evidence,
            "disclosure": "OI/volume do not independently prove institutional activity or delivery"}


def _pivots(values: list[float], radius: int = 2) -> list[tuple[int, str, float]]:
    result = []
    for i in range(radius, len(values) - radius):
        window = values[i-radius:i+radius+1]
        if values[i] == min(window) and window.count(values[i]) == 1:
            result.append((i, "L", values[i]))
        elif values[i] == max(window) and window.count(values[i]) == 1:
            result.append((i, "H", values[i]))
    return result


def classify_price_pattern(bars: Iterable[dict], tolerance_pct: float = 3.0) -> dict:
    """Identify U/V recovery, N double-top risk, or W double-bottom structure."""
    rows = sorted(list(bars), key=lambda r: str(r.get("date") or r.get("start_time") or ""))
    if len(rows) < 9:
        return {"pattern": "NONE", "state": "DATA_INSUFFICIENT", "confidence": 0.0}
    closes = [float(r["close"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    pivots = _pivots(closes, 2)
    recent = pivots[-5:]
    lows_p = [(i, v) for i, kind, v in recent if kind == "L"]
    highs_p = [(i, v) for i, kind, v in recent if kind == "H"]
    last = closes[-1]
    if len(lows_p) >= 2 and len(highs_p) >= 1:
        (l1i, l1), (l2i, l2) = lows_p[-2:]
        middle = [v for i, v in highs_p if l1i < i < l2i]
        if middle:
            neckline = max(middle)
            similar_lows = abs(l2-l1) / max(l1, l2) * 100 <= tolerance_pct
            if similar_lows:
                confirmed = last > neckline
                return {"pattern": "W", "state": "CONFIRMED_BULLISH_BREAKOUT" if confirmed else "DEVELOPING",
                        "support_zone": [min(l1, l2), max(l1, l2)], "neckline": neckline,
                        "invalidation_level": min(l1, l2), "confidence": 0.9 if confirmed else 0.65}
    if len(highs_p) >= 2:
        (h1i, h1), (h2i, h2) = highs_p[-2:]
        neckline_candidates = [v for i, kind, v in recent if kind == "L" and h1i < i < h2i]
        similar_highs = abs(h2-h1) / max(h1, h2) * 100 <= tolerance_pct
        if similar_highs and neckline_candidates:
            neckline = min(neckline_candidates)
            return {"pattern": "N", "state": "CONFIRMED_DOUBLE_TOP_BREAKDOWN" if last < neckline else "DEVELOPING_RISK",
                    "resistance_zone": [min(h1, h2), max(h1, h2)], "neckline": neckline,
                    "invalidation_level": max(h1, h2), "confidence": 0.85 if last < neckline else 0.6}
    recent_closes = closes[-9:]
    low_idx = min(range(len(recent_closes)), key=recent_closes.__getitem__)
    if 1 < low_idx < len(recent_closes)-2 and recent_closes[-1] > recent_closes[low_idx]:
        recovery = (recent_closes[-1] / recent_closes[low_idx] - 1) * 100
        before = recent_closes[:low_idx+1]
        shape = "V" if low_idx <= 3 and recovery >= 5 else "U" if low_idx >= 3 and recovery >= 3 else None
        if shape:
            return {"pattern": shape, "state": "RECOVERY_DEVELOPING",
                    "trough": recent_closes[low_idx], "recovery_pct": round(recovery, 2),
                    "invalidation_level": min(lows[-5:]), "confidence": 0.55}
    return {"pattern": "NONE", "state": "NO_QUALIFIED_PATTERN", "confidence": 0.0}


def evaluate_monthly_cycle(payload: dict) -> dict:
    """Evaluate one instrument snapshot; caller supplies exchange calendar and normalized bars."""
    selected = select_reference_session(payload["year"], payload["month"], payload.get("exchange_sessions", []))
    if not selected["reference_date"]:
        return {"status": "DATA_INSUFFICIENT", "reference": selected}
    reference = monthly_reference(payload.get("monthly_bars", []), selected["reference_date"])
    if reference.get("status") != "REFERENCE_CAPTURED":
        return {"status": "DATA_INSUFFICIENT", "reference": selected, "monthly_reference": reference}
    hold = evaluate_two_session_hold(payload.get("daily_bars", []), selected["reference_date"], reference["pml"])
    close = payload.get("monthly_close")
    pattern = classify_price_pattern(payload.get("daily_bars", []))
    return {"status": hold["status"], "reference": selected, "monthly_reference": reference,
            "support_acceptance": hold,
            "premium_discount": classify_premium_discount(float(close), reference["pml"], reference["pmh"]) if close is not None else "DATA_INSUFFICIENT",
            "pattern": pattern, "instrument_type": payload.get("instrument_type", "EQUITY"),
            "as_of": payload.get("as_of"), "tags": ["23RD_FORECAST", "MONTH_END_ACTUAL", "HISTORICAL"]}
