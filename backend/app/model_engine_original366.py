"""AIR ORIGINAL366 lifecycle replay for explicitly qualified option entries."""
from __future__ import annotations
from datetime import date
from typing import Any

ORIGINAL366_RULES = {
    "membership": "Only explicitly tagged ORIGINAL366 candidates are evaluated; no membership is inferred from other strategies.",
    "entry": "Use verified original entry_date and entry_price on the signal record; this evaluator does not regenerate the historical entry signal.",
    "stock_premium": "New stock CE/PE candidates must have entry premium ₹1–₹10 inclusive. Index options are exempt from the ₹10 cap. Historical baseline remains unchanged.",
    "stop_loss": "5% below original entry premium. Check daily option LOW from entry day through expiry. Same-day breach exits at the stop; later gap-through exits at observed session OPEN when below stop; otherwise exit at stop.",
    "expiry_winner": "If no stop is hit, value at verified expiry-day intrinsic value. A winner requires intrinsic value strictly greater than entry premium.",
    "expiry_loss": "If no stop is hit and expiry intrinsic value is less than or equal to entry premium, classify as EXPIRED_LOSS.",
    "pnl": "Rupee P&L requires explicit position_quantity and charges_rupees evidence; neither is inferred from traded volume.",
    "evidence": "Daily option OHLCV bars plus expiry-day underlying_close are required for complete replay.",
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
    if entry_day >= expiry_day or entry_price is None or entry_price <= 0 or strike is None or strike <= 0 or option_type not in {"CE", "PE"}:
        return {"status": "REJECTED", "reason": "Invalid entry/expiry dates, entry premium, strike or option type", "trades": [], "rules": ORIGINAL366_RULES}
    if stock and not 1.0 <= entry_price <= 10.0:
        return {"status": "REJECTED", "reason": "New stock-option entry premium is outside ₹1–₹10", "trades": [], "rules": ORIGINAL366_RULES}
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
    qty = _number(contract.get("position_quantity") or evidence.get("position_quantity"))
    trade = {
        "strategy": "ORIGINAL366", "signal_id": contract.get("signal_id"),
        "symbol": contract.get("symbol"), "instrument_type": instrument,
        "option_type": option_type, "strike": strike, "expiry": expiry_day.isoformat(),
        "signal_date": contract.get("signal_date"), "entry_date": entry_day.isoformat(),
        "entry_price": entry_price, "stop_loss": stop, "exit_date": exit_day,
        "exit_price": round(exit_price, 4) if exit_price is not None else None,
        "exit_reason": exit_reason, "classification": None, "expiry_intrinsic": None,
        "expiry_underlying_close": None, "pnl_points": None,
        "position_quantity": qty, "gross_pnl_rupees": None, "charges_rupees": None, "net_pnl_rupees": None,
    }
    if exit_reason:
        trade.update({"classification": "SLHIT", "pnl_points": round(exit_price-entry_price, 4)})
    elif cutoff < expiry_day:
        trade.update({"classification": "HOLD", "reason": "Original entry remains active; no verified 5% stop breach through replay cutoff"})
    elif expiry_bar is None or _number(expiry_bar.get("underlying_close")) is None:
        trade.update({"classification": "WAIT", "reason": "Expiry reached but verified expiry-day underlying close is missing"})
    else:
        underlying = float(expiry_bar["underlying_close"])
        intrinsic = _intrinsic(option_type, strike, underlying)
        trade.update({
            "classification": "EXPIRED_WIN" if intrinsic > entry_price else "EXPIRED_LOSS",
            "exit_date": expiry_day.isoformat(), "exit_price": round(intrinsic, 4),
            "exit_reason": "EXPIRY_INTRINSIC_SETTLEMENT", "expiry_intrinsic": round(intrinsic, 4),
            "expiry_underlying_close": underlying, "pnl_points": round(intrinsic-entry_price, 4),
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
        "data_quality": {"raw_bars": len(raw), "valid_bars": len(bars),
                         "expiry_day_bar_available": expiry_bar is not None,
                         "expiry_underlying_close_available": bool(expiry_bar and _number(expiry_bar.get("underlying_close")) is not None)},
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
        if not (evidence.get("daily_option_bars") or evidence.get("daily_bars")):
            continue
        evaluated.append({**row, "original366": evaluate_original366_contract(row, as_of=as_of)})
    return evaluated
