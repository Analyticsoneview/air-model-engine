"""AIR ORIGINAL366: original-entry RECOVERED watch with retrospective 10%/45% exits."""
from __future__ import annotations

from datetime import date
from typing import Any

ORIGINAL366_RULES = {
    "cohort": "RECOVERED is the display section for the ORIGINAL366 reference cohort: 366 full-expiry-coverage entries selected from the original 534-entry population; 83 partial-coverage and 85 no-post-entry-data records remain outside this cohort.",
    "entry": "Use actual filled entry_date and entry_price. CE and PE contracts are evaluated independently.",
    "stock_premium": "New stock CE/PE entries require premium ₹1–₹10 inclusive. Index options are exempt from the ₹10 cap.",
    "minimum_shelf_life": "At least 10 verified NSE trading sessions must remain from actual filled entry to expiry. Supply remaining_trading_sessions on the row or in evidence; calendar days and weekday estimates are not substituted.",
    "stop_loss": "The original ORIGINAL366 lifecycle retains its historical 5% stop and SLHIT classification.",
    "recovered_watch": "After the original 5% stop, a subsequent verified daily option CLOSE strictly above original entry qualifies a RECOVERED watch. For this retrospective alternative exit model, retain the ORIGINAL366 entry price and replay all daily bars from original entry with 10% SL and 45% target. If both touch in one candle, stop first. Keep original 5% SLHIT unchanged; this watch is not a new entry or order.",
    "expiry": "If no 5% stop occurs, settle using verified expiry-day underlying reference close and CE/PE intrinsic value. Keep expiry winners and losses under EXPIRED.",
    "unresolved": "Missing entry qualification, daily option bars, or verified expiry reference remains WAIT/UNRESOLVED and is never presented as a qualified active contract or completed historical trade.",
    "pnl": "Rupee P&L requires explicit position_quantity; net P&L additionally requires explicit charges_rupees.",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _valid_bar(bar: dict[str, Any]) -> bool:
    vals = [_number(bar.get(k)) for k in ("open", "high", "low", "close", "quantity")]
    if any(v is None or v <= 0 for v in vals):
        return False
    op, high, low, close, quantity = vals
    return high >= max(op, low, close) and low <= min(op, close)


def _intrinsic(option_type: str, strike: float, underlying_close: float) -> float:
    return max(underlying_close - strike, 0.0) if option_type == "CE" else max(strike - underlying_close, 0.0)


def _remaining_sessions(contract: dict[str, Any], evidence: dict[str, Any]) -> float | None:
    # The recovered MFE/MAE workbook names this source field shelf_sessions.
    value = contract.get("remaining_trading_sessions")
    if value is None:
        value = contract.get("shelf_sessions")
    if value is None:
        value = evidence.get("remaining_trading_sessions")
    if value is None:
        value = evidence.get("shelf_sessions")
    return _number(value)


def _recovered_exit_model(bars: list[dict[str, Any]], *, entry_price: float, option_type: str, strike: float, expiry_day: date, cutoff: date) -> dict[str, Any]:
    """Retrospective alternate exits from ORIGINAL entry price, never a new fill."""
    stop = round(entry_price * 0.90, 4)
    target = round(entry_price * 1.45, 4)
    for bar in bars:
        day = date.fromisoformat(bar["date"])
        if day > cutoff:
            continue
        op, high, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
        if op <= stop:
            exit_price, reason, outcome = op, "GAP_THROUGH_10_PERCENT_STOP", "STOP_FIRST"
        elif op >= target:
            exit_price, reason, outcome = op, "GAP_THROUGH_45_PERCENT_TARGET", "TARGET_FIRST"
        elif low <= stop and high >= target:
            exit_price, reason, outcome = stop, "SAME_CANDLE_STOP_FIRST", "STOP_FIRST"
        elif low <= stop:
            exit_price, reason, outcome = stop, "10_PERCENT_STOP", "STOP_FIRST"
        elif high >= target:
            exit_price, reason, outcome = target, "45_PERCENT_TARGET", "TARGET_FIRST"
        else:
            continue
        return {
            "entry_price": entry_price, "stop_loss": stop, "target": target,
            "exit_date": bar["date"], "exit_price": round(exit_price, 4),
            "exit_reason": reason, "outcome": outcome,
            "pnl_points": round(exit_price - entry_price, 4),
            "return_pct": round((exit_price / entry_price - 1) * 100, 4),
            "simulation_basis": "ORIGINAL_ENTRY_PRICE_RETROSPECTIVE_EXIT_MODEL",
            "same_candle_policy": "STOP_FIRST",
        }
    expiry_bar = next((b for b in bars if b["date"] == expiry_day.isoformat() and date.fromisoformat(b["date"]) <= cutoff), None)
    if expiry_bar and _number(expiry_bar.get("underlying_close")) is not None:
        intrinsic = _intrinsic(option_type, strike, float(expiry_bar["underlying_close"]))
        return {
            "entry_price": entry_price, "stop_loss": stop, "target": target,
            "exit_date": expiry_bar["date"], "exit_price": round(intrinsic, 4),
            "exit_reason": "EXPIRY_INTRINSIC_NO_TARGET_OR_STOP",
            "outcome": "EXPIRY_SETTLEMENT", "pnl_points": round(intrinsic - entry_price, 4),
            "return_pct": round((intrinsic / entry_price - 1) * 100, 4),
            "simulation_basis": "ORIGINAL_ENTRY_PRICE_RETROSPECTIVE_EXIT_MODEL",
            "same_candle_policy": "STOP_FIRST",
        }
    return {
        "entry_price": entry_price, "stop_loss": stop, "target": target,
        "exit_date": None, "exit_price": None, "exit_reason": None,
        "outcome": "UNRESOLVED", "pnl_points": None, "return_pct": None,
        "simulation_basis": "ORIGINAL_ENTRY_PRICE_RETROSPECTIVE_EXIT_MODEL",
        "same_candle_policy": "STOP_FIRST",
    }


def evaluate_original366_contract(contract: dict[str, Any], *, as_of: str | None = None) -> dict[str, Any]:
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    try:
        expiry_day = date.fromisoformat(str(contract.get("expiry") or "")[:10])
        entry_day = date.fromisoformat(str(contract.get("entry_date") or "")[:10])
        cutoff = date.fromisoformat(str(as_of)[:10]) if as_of else date.today()
    except ValueError:
        return {"status": "REJECTED", "reason": "Missing or invalid entry/expiry/as_of date", "trades": [], "rules": ORIGINAL366_RULES}

    entry_price = _number(contract.get("entry_price"))
    strike = _number(contract.get("strike"))
    option_type = str(contract.get("option_type") or "").upper()
    instrument = str(contract.get("instrument_type") or "").upper()
    stock = instrument in {"STOCK", "EQUITY", "OPTSTK", "STOCK_OPTION"} and option_type in {"CE", "PE"}
    sessions = _remaining_sessions(contract, evidence)

    if entry_day >= expiry_day or entry_price is None or entry_price <= 0 or strike is None or strike <= 0 or option_type not in {"CE", "PE"}:
        return {"status": "REJECTED", "reason": "Invalid entry/expiry dates, entry premium, strike or option type", "trades": [], "rules": ORIGINAL366_RULES}
    if stock and not 1.0 <= entry_price <= 10.0:
        return {"status": "REJECTED", "reason": "New stock-option entry premium is outside ₹1–₹10", "trades": [], "rules": ORIGINAL366_RULES}
    if sessions is None or sessions < 10:
        return {
            "status": "REJECTED",
            "reason": "At least 10 verified NSE trading sessions must remain at actual entry",
            "trades": [],
            "rules": ORIGINAL366_RULES,
            "data_quality": {"remaining_trading_sessions": sessions, "minimum_required": 10},
        }

    raw = evidence.get("daily_option_bars") or evidence.get("daily_bars") or []
    bars = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("date") or not _valid_bar(item):
            continue
        try:
            day = date.fromisoformat(str(item["date"])[:10])
        except ValueError:
            continue
        if entry_day <= day <= expiry_day and day <= cutoff:
            bars.append({**item, "date": day.isoformat()})
    bars.sort(key=lambda x: x["date"])
    expiry_bar = next((x for x in bars if x["date"] == expiry_day.isoformat()), None)
    stop = round(entry_price * 0.95, 4)
    exit_day = exit_price = exit_reason = None

    for bar in bars:
        day = date.fromisoformat(bar["date"])
        if float(bar["low"]) <= stop:
            exit_day = bar["date"]
            exit_price = float(bar["open"]) if day > entry_day and float(bar["open"]) < stop else stop
            exit_reason = "SAME_DAY_STOP" if day == entry_day else ("GAP_THROUGH_STOP" if float(bar["open"]) < stop else "STOP_LOSS")
            break
        if day >= expiry_day:
            break

    # A post-stop close above the original entry premium is a watch-only
    # recovery observation. It does not reverse the original SLHIT or create
    # a position/re-entry. A daily HIGH alone is deliberately insufficient.
    recovered_watch = None
    if exit_day is not None:
        for bar in bars:
            if bar["date"] > exit_day and _number(bar.get("close")) is not None and float(bar["close"]) > entry_price:
                recovered_watch = {
                    "trigger_date": bar["date"],
                    "trigger_close": float(bar["close"]),
                    "reference_entry_price": entry_price,
                    "condition": "DAILY_CLOSE_ABOVE_ORIGINAL_ENTRY_AFTER_5_PERCENT_SL",
                    "exit_model": _recovered_exit_model(
                        bars, entry_price=entry_price, option_type=option_type,
                        strike=strike, expiry_day=expiry_day, cutoff=cutoff,
                    ),
                    "watch_only": True,
                    "is_reentry": False,
                    "is_open_position": False,
                }
                break

    qty = _number(contract.get("position_quantity") or evidence.get("position_quantity"))
    trade = {
        "strategy": "ORIGINAL366", "signal_id": contract.get("signal_id"),
        "symbol": contract.get("symbol"), "instrument_type": instrument,
        "option_type": option_type, "strike": strike, "expiry": expiry_day.isoformat(),
        "signal_date": contract.get("signal_date"), "entry_date": entry_day.isoformat(),
        "entry_price": entry_price, "remaining_trading_sessions_at_entry": sessions,
        "stop_loss": stop, "exit_date": exit_day,
        "exit_price": round(exit_price, 4) if exit_price is not None else None,
        "exit_reason": exit_reason, "classification": None, "expiry_intrinsic": None,
        "expiry_underlying_close": None, "pnl_points": None,
        "position_quantity": qty, "gross_pnl_rupees": None, "charges_rupees": None, "net_pnl_rupees": None,
        "recovered_watch": recovered_watch,
    }

    if exit_reason:
        trade.update({"classification": "SLHIT", "pnl_points": round(exit_price - entry_price, 4)})
    elif not bars:
        trade.update({"classification": "WAIT", "reason": "No valid daily option OHLCV is available from entry date"})
    elif cutoff < expiry_day:
        trade.update({
            "classification": "NEW" if entry_day == cutoff else "HOLD",
            "reason": "Qualified ORIGINAL366 entry remains active; no verified 5% stop breach through replay cutoff",
        })
    elif expiry_bar is None or _number(expiry_bar.get("underlying_close")) is None:
        trade.update({"classification": "WAIT", "reason": "Expiry reached but verified expiry-day underlying reference close is missing"})
    else:
        underlying = float(expiry_bar["underlying_close"])
        intrinsic = _intrinsic(option_type, strike, underlying)
        trade.update({
            "classification": "EXPIRED_WIN" if intrinsic > entry_price else "EXPIRED_LOSS",
            "exit_date": expiry_day.isoformat(), "exit_price": round(intrinsic, 4),
            "exit_reason": "EXPIRY_INTRINSIC_SETTLEMENT", "expiry_intrinsic": round(intrinsic, 4),
            "expiry_underlying_close": underlying, "pnl_points": round(intrinsic - entry_price, 4),
        })

    if qty is not None and trade["pnl_points"] is not None:
        trade["gross_pnl_rupees"] = round(trade["pnl_points"] * qty, 2)
        charges = _number(evidence.get("charges_rupees"))
        if charges is not None:
            trade["charges_rupees"] = charges
            trade["net_pnl_rupees"] = round(trade["gross_pnl_rupees"] - charges, 2)

    return {
        "status": trade["classification"], "reason": trade.get("reason") or trade.get("exit_reason"),
        "trades": [trade], "trade_count": 1, "rules": ORIGINAL366_RULES,
        "data_quality": {
            "raw_bars": len(raw), "valid_bars": len(bars),
            "remaining_trading_sessions": sessions,
            "expiry_day_bar_available": expiry_bar is not None,
            "expiry_underlying_close_available": bool(expiry_bar and _number(expiry_bar.get("underlying_close")) is not None),
        },
    }


def evaluate_original366_rows(rows: list[dict[str, Any]], *, as_of: str | None = None) -> list[dict[str, Any]]:
    evaluated = []
    for row in rows:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        memberships = evidence.get("strategy_memberships") or evidence.get("strategies") or []
        if isinstance(memberships, str):
            memberships = [memberships]
        normalized = {str(x).upper().replace(" ", "") for x in memberships}
        strategy = str(evidence.get("strategy") or row.get("strategy") or "").upper().replace(" ", "")
        if "ORIGINAL366" not in normalized and strategy != "ORIGINAL366":
            continue
        # Keep tagged records visible as WAIT/REJECTED when evidence is missing;
        # silently dropping them would make the qualified cohort look larger.
        evaluated.append({**row, "original366": evaluate_original366_contract(row, as_of=as_of)})
    return evaluated
