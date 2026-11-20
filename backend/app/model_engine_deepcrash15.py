"""AIR DEEPCRASH15: historical premium-collapse recovery watchlist.

Research-only screen over verified daily NSE FO option bars. It identifies
contracts whose observed premium high was ₹3,000–₹3,500 and whose latest
completed close is below ₹50, with at least 15 remaining FO trading sessions.
It is a watchlist, not an entry or order signal.
"""
from __future__ import annotations

from datetime import date
from typing import Any

ENGINE_VERSION = "DEEPCRASH15_DAILY_OHLC_V2"
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
    "consolidation": "The six completed sessions immediately before the bullish setup candle must have a combined HIGH-to-LOW range no wider than 10 premium points",
    "entry": "After the six-session consolidation and a bullish setup candle (CLOSE > OPEN), enter at the next completed session CLOSE only when that CLOSE is greater than the setup candle CLOSE",
    "holding": "After entry, hold the option position through expiry; use the verified option CLOSE on the expiry date as the recorded exit value. Do not synthesize a missing expiry valuation",
    "execution": "Modelled entry/hold lifecycle only; no broker order is placed",
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



def _remaining_fo_sessions(as_of_text: str, expiry_text: str) -> int | None:
    """Count future FO sessions using persisted NSE FO holiday masters only."""
    try:
        start = date.fromisoformat(as_of_text[:10])
        expiry = date.fromisoformat(expiry_text[:10])
    except (TypeError, ValueError):
        return None
    if expiry <= start:
        return 0
    try:
        from app.nse_bhavcopy import _get_store
        store = _get_store()
        holidays: set[str] = set()
        for year in range(start.year, expiry.year + 1):
            calendar = store.get_meta(f"trading_calendar_{year}")
            if not isinstance(calendar, dict):
                return None
            fo = (calendar.get("segments") or {}).get("FO")
            if not isinstance(fo, list):
                return None
            holidays.update(str(item.get("date"))[:10] for item in fo if isinstance(item, dict) and item.get("date"))
    except Exception:
        return None
    sessions = 0
    current = date.fromordinal(start.toordinal() + 1)
    while current <= expiry:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            sessions += 1
        current = date.fromordinal(current.toordinal() + 1)
    return sessions


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
    if remaining is None and contract.get("expiry"):
        remaining = _remaining_fo_sessions(latest["date"], str(contract.get("expiry")))
    try:
        remaining = int(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining = None

    checks = {
        "historical_peak_in_range": MIN_PEAK <= peak <= MAX_PEAK,
        "latest_close_below_50": latest_close < MAX_LATEST_CLOSE,
        "at_least_15_trading_sessions": remaining is not None and remaining >= MIN_REMAINING_SESSIONS,
        "latest_candle_bullish": latest_close > float(latest["open"]),
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
    # If an expiry-day bar is present, evaluate the immediately preceding
    # completed session as the breakout confirmation; otherwise use the latest
    # available session. The setup candle is the session before confirmation.
    entry = None
    consolidation = {"status": "WAIT", "reason": "Need six consolidation sessions, a bullish setup candle and the following session"}
    expiry_bar = next((item for item in bars if expiry and item["date"] == expiry), None)
    confirmation_index = len(bars) - 1
    if expiry_bar is not None:
        confirmation_index = bars.index(expiry_bar) - 1
    if confirmation_index >= 7:
        consolidation_bars = bars[confirmation_index - 7:confirmation_index - 1]
        setup_bar = bars[confirmation_index - 1]
        trigger_bar = bars[confirmation_index]
        range_high = max(float(item["high"]) for item in consolidation_bars)
        range_low = min(float(item["low"]) for item in consolidation_bars)
        range_width = round(range_high - range_low, 4)
        bullish_setup = float(setup_bar["close"]) > float(setup_bar["open"])
        next_close_confirmed = float(trigger_bar["close"]) > float(setup_bar["close"])
        consolidation = {
            "status": "QUALIFIED" if range_width <= 10.0 and bullish_setup else "REJECTED",
            "lookback_sessions": 6,
            "lookback_start": consolidation_bars[0]["date"],
            "lookback_end": consolidation_bars[-1]["date"],
            "range_high": round(range_high, 4),
            "range_low": round(range_low, 4),
            "range_width": range_width,
            "max_range_points": 10.0,
            "setup_date": setup_bar["date"],
            "setup_open": float(setup_bar["open"]),
            "setup_close": float(setup_bar["close"]),
            "setup_bullish": bullish_setup,
            "confirmation_date": trigger_bar["date"],
            "confirmation_close": float(trigger_bar["close"]),
            "next_close_above_setup_close": next_close_confirmed,
        }
        if range_width <= 10.0 and bullish_setup and next_close_confirmed:
            entry = {
                "entry_date": trigger_bar["date"],
                "entry_price": float(trigger_bar["close"]),
            }

    position_status = "WATCH"
    exit_price = None
    exit_date = None
    if entry:
        position_status = "OPEN"
        if expiry_bar and expiry_bar["date"] >= entry["entry_date"]:
            position_status = "EXPIRED"
            exit_price = float(expiry_bar["close"])
            exit_date = expiry_bar["date"]
    return {
        "status": "QUALIFIED",
        "position_status": position_status,
        "classification": position_status,
        "consolidation": consolidation,
        "entry_date": entry["entry_date"] if entry else None,
        "entry_price": round(entry["entry_price"], 4) if entry else None,
        "exit_date": exit_date,
        "exit_price": round(exit_price, 4) if exit_price is not None else None,
        "hold_rule": "HOLD_TO_EXPIRY",
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
        "reason": ("Entry confirmed on next-session close; hold through verified expiry close" if entry else "Premium-crash qualification passed; waiting for six-session consolidation and next-close confirmation"),
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
