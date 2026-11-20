"""AIR DEEPCRASH15: historical premium-collapse recovery watchlist.

Research-only screen over verified daily NSE FO option bars. It identifies
contracts whose observed premium high was ₹3,000–₹3,500 and whose latest
completed close is below ₹50, with at least 15 remaining FO trading sessions.
It is a watchlist, not an entry or order signal.
"""
from __future__ import annotations

from datetime import date
from typing import Any

ENGINE_VERSION = "DEEPCRASH15_DAILY_OHLC_V1"
MIN_PEAK = 3000.0
MAX_PEAK = 3500.0
MAX_LATEST_CLOSE = 50.0
MIN_REMAINING_SESSIONS = 15

RULES = {
    "historical_peak_premium": "Maximum verified daily option HIGH across retained history must be ₹3,000–₹3,500 inclusive",
    "latest_premium": "Most recent completed valid daily option CLOSE must be below ₹50",
    "expiry_shelf_life": "At least 15 remaining NSE FO trading sessions, sourced from the exchange trading calendar; missing session count is not inferred",
    "latest_candle": "Most recent completed valid daily candle must close above its open",
    "scope": "CE and PE contracts evaluated independently; historical bars must belong to the same exact contract",
    "execution": "Research watchlist only; no automatic entry, position, alert or broker order is created",
}


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number or number == float("inf"):
        return None
    return number


def _valid_bar(bar: dict[str, Any]) -> bool:
    op, high, low, close = (_positive(bar.get(key)) for key in ("open", "high", "low", "close"))
    return bool(op is not None and high is not None and low is not None and close is not None
                and high >= max(op, close, low) and low <= min(op, close))


def evaluate_deepcrash15_contract(
    contract: dict[str, Any], *, as_of: str | None = None
) -> dict[str, Any]:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    raw_bars = evidence.get("daily_option_bars") or evidence.get("daily_bars") or []
    bars = []
    for raw in raw_bars:
        if not isinstance(raw, dict) or not raw.get("date") or not _valid_bar(raw):
            continue
        try:
            day = date.fromisoformat(str(raw["date"])[:10])
        except ValueError:
            continue
        if as_of and day > date.fromisoformat(str(as_of)[:10]):
            continue
        bars.append({**raw, "date": day.isoformat()})
    bars.sort(key=lambda item: item["date"])
    option_type = str(contract.get("option_type") or "").upper()
    if option_type not in {"CE", "PE"}:
        return {"status": "REJECTED", "reason": "Contract option type must be CE or PE"}
    if not bars:
        return {"status": "WAIT", "reason": "No verified daily option OHLC bars available"}

    peak_bar = max(bars, key=lambda item: float(item["high"]))
    latest = bars[-1]
    peak = float(peak_bar["high"])
    latest_close = float(latest["close"])
    remaining = contract.get("remaining_trading_sessions")
    if remaining is None:
        remaining = evidence.get("remaining_trading_sessions")
    try:
        remaining = int(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining = None

    checks = {
        "historical_peak_in_range": MIN_PEAK <= peak <= MAX_PEAK,
        "latest_close_below_50": latest_close < MAX_LATEST_CLOSE,
        "at_least_15_trading_sessions": remaining is not None and remaining >= MIN_REMAINING_SESSIONS,
        "latest_candle_bullish": float(latest["close"]) > float(latest["open"]),
    }
    missing = []
    if remaining is None:
        missing.append("verified remaining_trading_sessions from NSE FO trading calendar")
    if not all(checks.values()):
        return {
            "status": "REJECTED" if not missing else "WAIT",
            "reason": "One or more qualification rules did not pass" if not missing else "Trading-session shelf-life evidence is missing",
            "checks": checks,
            "missing_evidence": missing,
            "historical_peak_premium": round(peak, 4),
            "latest_close": round(latest_close, 4),
            "latest_bar_date": latest["date"],
            "remaining_trading_sessions": remaining,
            "rules": RULES,
        }

    expiry = str(contract.get("expiry") or "")[:10]
    return {
        "status": "QUALIFIED",
        "classification": "WATCH",
        "position_status": "WATCH_ONLY_NOT_OPEN",
        "strategy": "DEEPCRASH15",
        "strategy_version": ENGINE_VERSION,
        "signal_date": latest["date"],
        "symbol": contract.get("symbol"),
        "instrument_type": contract.get("instrument_type"),
        "option_type": option_type,
        "strike": contract.get("strike"),
        "expiry": expiry or None,
        "historical_peak_premium": round(peak, 4),
        "historical_peak_date": peak_bar["date"],
        "latest_open": float(latest["open"]),
        "latest_close": latest_close,
        "latest_bar_date": latest["date"],
        "premium_decline_pct": round((1 - latest_close / peak) * 100, 4),
        "remaining_trading_sessions": remaining,
        "checks": checks,
        "rules": RULES,
        "reason": "All four DEEPCRASH15 qualification rules passed; watchlist only, not an entry instruction",
    }


def evaluate_deepcrash15_rows(rows: list[dict[str, Any]], *, as_of: str | None = None) -> list[dict[str, Any]]:
    results = []
    for row in rows:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        if not (evidence.get("daily_option_bars") or evidence.get("daily_bars")):
            continue
        result = evaluate_deepcrash15_contract(row, as_of=as_of)
        if result.get("status") == "QUALIFIED":
            results.append({**row, **result})
    results.sort(key=lambda item: (
        str(item.get("signal_date") or ""),
        -float(item.get("historical_peak_premium") or 0),
        str(item.get("symbol") or ""),
        str(item.get("option_type") or ""),
    ), reverse=True)
    return results
