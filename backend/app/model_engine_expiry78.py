"""Deterministic AIR EXPIRY78 seven-rule backtest and lifecycle evaluator.

The evaluator consumes verified daily option OHLCV bars. It is research-only:
it does not submit orders or fabricate missing market/quantity evidence.
"""
from __future__ import annotations

from datetime import date
from typing import Any

RULES = {
    "valid_ohlcv": "O/H/L/C and quantity must be positive; high/low must contain open and close",
    "bullish_engulfing": "Current bullish candle body engulfs the previous bearish candle body",
    "entry_limit": "40% of the bullish-engulfing candle HIGH (high * 0.40)",
    "entry_fill": "A later daily LOW must touch or cross the limit before expiry; fill at the limit",
    "minimums": "Entry premium >= ₹1 and entry-day quantity >= 10; stock CE/PE entry premium must also be ₹1–₹10; index options are exempt from the ₹10 cap",
    "stop_loss": "5% below actual entry; evaluate daily LOW including entry day; if a later session opens below SL, exit at that OPEN, otherwise at SL",
    "expiry_survivor": "Only a trade that never hit SL and reaches expiry with verified underlying expiry close/intrinsic valuation is an EXPIRY78 survivor",
}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _valid_bar(bar: dict[str, Any]) -> bool:
    values = [_num(bar.get(key)) for key in ("open", "high", "low", "close", "quantity")]
    if any(value is None or value <= 0 for value in values):
        return False
    op, high, low, close, quantity = values
    return high >= max(op, close, low) and low <= min(op, close)


def _bullish_engulfing(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    po, pc = float(previous["open"]), float(previous["close"])
    co, cc = float(current["open"]), float(current["close"])
    return pc < po and cc > co and co <= pc and cc >= po


def _intrinsic(option_type: str, strike: float, underlying_close: float) -> float:
    if option_type == "CE":
        return max(underlying_close - strike, 0.0)
    if option_type == "PE":
        return max(strike - underlying_close, 0.0)
    raise ValueError("option_type must be CE or PE")


def evaluate_expiry78_contract(
    contract: dict[str, Any], *, as_of: str | None = None
) -> dict[str, Any]:
    """Replay all qualifying bullish-engulfing setups for one option contract.

    Expected evidence.daily_option_bars is a date-ordered or unordered list of
    daily option OHLCV dictionaries. Expiry settlement requires an expiry-day
    bar with underlying_close. Quantity used for the rule-5 volume threshold is
    the option bar's traded quantity; P&L uses position_quantity only.
    """
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    bars_raw = evidence.get("daily_option_bars") or evidence.get("daily_bars") or []
    expiry_text = str(contract.get("expiry") or "")[:10]
    try:
        expiry_day = date.fromisoformat(expiry_text)
    except ValueError:
        return {"status": "REJECTED", "reason": "Missing or invalid expiry date", "trades": [], "rules": RULES}
    try:
        as_of_day = date.fromisoformat(str(as_of)[:10]) if as_of else max(
            (date.fromisoformat(str(b.get("date"))[:10]) for b in bars_raw
             if isinstance(b, dict) and b.get("date")),
            default=date.today(),
        )
    except ValueError:
        return {"status": "REJECTED", "reason": "Invalid as_of date", "trades": [], "rules": RULES}

    bars: list[dict[str, Any]] = []
    for raw in bars_raw:
        if not isinstance(raw, dict) or not raw.get("date") or not _valid_bar(raw):
            continue
        try:
            day = date.fromisoformat(str(raw["date"])[:10])
        except ValueError:
            continue
        if day <= expiry_day and day <= as_of_day:
            bars.append({**raw, "date": day.isoformat()})
    bars.sort(key=lambda item: item["date"])

    option_type = str(contract.get("option_type") or "").upper()
    instrument_type = str(contract.get("instrument_type") or "").upper()
    is_stock_option = instrument_type in {"STOCK", "EQUITY"} and option_type in {"CE", "PE"}
    strike = _num(contract.get("strike"))
    if option_type not in {"CE", "PE"} or strike is None or strike <= 0:
        return {"status": "REJECTED", "reason": "Invalid option type or strike", "trades": [], "rules": RULES}

    trades: list[dict[str, Any]] = []
    valid_bars = [bar for bar in bars if date.fromisoformat(bar["date"]) < expiry_day]
    for index in range(1, len(valid_bars)):
        previous, engulfing = valid_bars[index - 1], valid_bars[index]
        if not _bullish_engulfing(previous, engulfing):
            continue
        limit_price = round(float(engulfing["high"]) * 0.40, 4)
        if limit_price < 1.0 or (is_stock_option and limit_price > 10.0):
            continue
        entry_bar = next(
            (bar for bar in valid_bars[index + 1:]
             if float(bar["low"]) <= limit_price and float(bar["quantity"]) >= 10),
            None,
        )
        if entry_bar is None:
            continue
        entry_day = date.fromisoformat(entry_bar["date"])
        if entry_day >= expiry_day:
            continue
        entry_price = limit_price
        stop = round(entry_price * 0.95, 4)
        exit_day = None
        exit_price = None
        exit_reason = None
        expiry_bar = next((bar for bar in bars if bar["date"] == expiry_day.isoformat()), None)

        # Daily-low stop check starts on the entry day. A same-day low breach
        # is conservatively treated as stopped. On later sessions a gap below
        # the stop exits at the observed open, not at the unavailable stop price.
        for bar in bars:
            day = date.fromisoformat(bar["date"])
            if day < entry_day:
                continue
            if float(bar["low"]) <= stop:
                exit_day = bar["date"]
                exit_price = (float(bar["open"]) if day > entry_day and float(bar["open"]) < stop else stop)
                exit_reason = "SAME_DAY_STOP" if day == entry_day else (
                    "GAP_THROUGH_STOP" if float(bar["open"]) < stop else "STOP_LOSS"
                )
                break
            if day >= expiry_day:
                break

        trade: dict[str, Any] = {
            "symbol": contract.get("symbol"),
            "instrument_type": instrument_type,
            "option_type": option_type,
            "strike": strike,
            "expiry": expiry_day.isoformat(),
            "signal_date": engulfing["date"],
            "engulfing_high": float(engulfing["high"]),
            "entry_limit": limit_price,
            "entry_date": entry_day.isoformat(),
            "entry_price": entry_price,
            "entry_day_quantity": float(entry_bar["quantity"]),
            "stop_loss": stop,
            "exit_date": exit_day,
            "exit_price": round(exit_price, 4) if exit_price is not None else None,
            "exit_reason": exit_reason,
            "expiry_survivor": False,
            "intrinsic_value": None,
            "pnl_points": None,
            "gross_pnl_rupees": None,
            "charges_rupees": None,
            "net_pnl_rupees": None,
        }
        if exit_reason:
            trade.update({"classification": "SL", "position_status": "EXITED",
                          "reason": exit_reason,
                          "pnl_points": round(exit_price - entry_price, 4)})
            position_quantity = _num(contract.get("position_quantity") or evidence.get("position_quantity"))
            if position_quantity is not None:
                trade["gross_pnl_rupees"] = round((exit_price - entry_price) * position_quantity, 2)
                charges = _num(evidence.get("charges_rupees"))
                if charges is not None:
                    trade["charges_rupees"] = charges
                    trade["net_pnl_rupees"] = round(trade["gross_pnl_rupees"] - charges, 2)
        elif expiry_day <= as_of_day and expiry_bar is not None and _num(expiry_bar.get("underlying_close")) is not None:
            intrinsic = _intrinsic(option_type, strike, float(expiry_bar["underlying_close"]))
            trade.update({
                "classification": "EXPIRED",
                "position_status": "EXPIRY_SURVIVOR",
                "expiry_survivor": True,
                "expiry_underlying_close": float(expiry_bar["underlying_close"]),
                "intrinsic_value": round(intrinsic, 4),
                "exit_date": expiry_day.isoformat(),
                "exit_price": round(intrinsic, 4),
                "exit_reason": "EXPIRY_INTRINSIC_SETTLEMENT",
                "pnl_points": round(intrinsic - entry_price, 4),
            })
            position_quantity = _num(contract.get("position_quantity") or evidence.get("position_quantity"))
            if position_quantity is not None:
                trade["gross_pnl_rupees"] = round((intrinsic - entry_price) * position_quantity, 2)
            charges = _num(evidence.get("charges_rupees"))
            if charges is not None and trade["gross_pnl_rupees"] is not None:
                trade["charges_rupees"] = charges
                trade["net_pnl_rupees"] = round(trade["gross_pnl_rupees"] - charges, 2)
        elif expiry_day <= as_of_day:
            trade.update({"classification": "WAIT", "position_status": "WAIT",
                          "reason": "Expiry reached but verified expiry-day underlying close is missing"})
        else:
            trade.update({"classification": "NEW" if entry_day == as_of_day else "HOLD", "position_status": "OPEN",
                          "reason": "Entry filled; daily low has not breached protected stop"})
        trades.append(trade)

    # Keep all historical setups: overlapping signals are separate trades. The
    # summary status is the most recent trade's state, or WAIT when no entry filled.
    trades.sort(key=lambda item: (item["signal_date"], item["entry_date"]))
    if trades:
        latest = trades[-1]
        status = latest["classification"]
        reason = latest.get("reason") or latest.get("exit_reason")
    else:
        status = "WAIT"
        reason = "No qualifying bullish-engulfing setup with a subsequent limit touch before expiry"
    return {
        "status": status,
        "reason": reason,
        "trades": trades,
        "trade_count": len(trades),
        "survivor_count": sum(bool(item["expiry_survivor"]) for item in trades),
        "stop_loss_count": sum(item["classification"] == "SL" for item in trades),
        "rules": RULES,
        "data_quality": {
            "raw_bars": len(bars_raw),
            "valid_bars": len(bars),
            "invalid_bars_excluded": max(0, len(bars_raw) - len(bars)),
            "expiry_day_bar_available": any(item["date"] == expiry_day.isoformat() for item in bars),
        },
    }


def evaluate_expiry78_rows(rows: list[dict[str, Any]], *, as_of: str | None = None) -> list[dict[str, Any]]:
    """Evaluate only explicitly EXPIRY78-member contracts with attached daily bars."""
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        memberships = evidence.get("strategy_memberships") or evidence.get("strategies") or []
        if isinstance(memberships, str):
            memberships = [memberships]
        strategy = str(evidence.get("strategy") or row.get("strategy") or "").upper().replace(" ", "")
        normalized = {str(value).upper().replace(" ", "") for value in memberships}
        if "EXPIRY78" not in normalized and strategy != "EXPIRY78" and evidence.get("expiry78_candidate") is not True:
            continue
        if not (evidence.get("daily_option_bars") or evidence.get("daily_bars")):
            continue
        result = evaluate_expiry78_contract(row, as_of=as_of)
        evaluated.append({**row, "expiry78": result})
    return evaluated
