"""AIR Model Engine P&L calendar aggregation with transparent estimated charges."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

# Indicative NSE equity-options charge model. Broker-specific tariffs and exchange
# circular changes should override these defaults; actual contract notes take priority.
RATES = {
    "brokerage_per_order": 20.0,
    "nse_options_transaction": 0.0003553,
    "sebi_turnover": 0.000001,
    "stamp_buy": 0.00003,
    "stt_sell_before_2026_04_01": 0.001,
    "stt_sell_from_2026_04_01": 0.0015,
    "stt_exercise_before_2026_04_01": 0.00125,
    "stt_exercise_from_2026_04_01": 0.0015,
    "gst": 0.18,
}


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def _charges(trade: dict[str, Any], quantity: float, entry: float,
             exit_price: float, exit_day: str) -> dict[str, Any]:
    evidence = trade.get("evidence") if isinstance(trade.get("evidence"), dict) else {}
    supplied = evidence.get("charges_breakdown")
    if isinstance(supplied, dict):
        components = {key: round(float(value), 2) for key, value in supplied.items()
                      if _num(value) is not None}
        total = round(sum(components.values()), 2)
        return {"total": total, "components": components, "basis": "ACTUAL_SOURCE_BREAKDOWN"}

    explicit = _num(evidence.get("charges_rupees"))
    if explicit is None:
        explicit = _num(trade.get("charges_rupees"))
    if explicit is not None:
        return {"total": round(explicit, 2),
                "components": {"broker_reported_total": round(explicit, 2)},
                "basis": "ACTUAL_REPORTED_TOTAL_BREAKDOWN_UNAVAILABLE"}

    buy_turnover = entry * quantity
    expiry_settlement = str(trade.get("exit_reason") or "").upper().startswith("EXPIRY_INTRINSIC")
    exercised = expiry_settlement and exit_price > 0
    sell_turnover = 0.0 if expiry_settlement else exit_price * quantity
    turnover = buy_turnover + sell_turnover
    # SEBI guidance: brokerage is not levied on expiry exercise/assignment;
    # an OTM worthless expiry also has no closing sell order.
    brokerage = (1 if expiry_settlement else 2) * RATES["brokerage_per_order"]
    exchange = turnover * RATES["nse_options_transaction"]
    sebi = turnover * RATES["sebi_turnover"]
    stamp = buy_turnover * RATES["stamp_buy"]
    cutoff = date(2026, 4, 1)
    if exercised:
        stt_rate = (RATES["stt_exercise_from_2026_04_01"] if date.fromisoformat(exit_day) >= cutoff
                    else RATES["stt_exercise_before_2026_04_01"])
        stt = exit_price * quantity * stt_rate
    elif expiry_settlement:
        stt = 0.0
    else:
        stt_rate = (RATES["stt_sell_from_2026_04_01"] if date.fromisoformat(exit_day) >= cutoff
                    else RATES["stt_sell_before_2026_04_01"])
        stt = sell_turnover * stt_rate
    gst = (brokerage + exchange + sebi) * RATES["gst"]
    components = {
        "brokerage": brokerage,
        "exchange_transaction_charges_nse_estimate": exchange,
        "sebi_turnover_fee": sebi,
        "stamp_duty_buy_side": stamp,
        "stt_sell_side": stt,
        "gst_on_brokerage_exchange_sebi": gst,
    }
    return {"total": round(sum(components.values()), 2),
            "components": {key: round(value, 2) for key, value in components.items()},
            "basis": "ESTIMATED_NSE_OPTIONS_ROUND_TRIP",
            "rates": dict(RATES)}


def _trade_record(row: dict[str, Any], strategy: str) -> dict[str, Any] | None:
    entry_date = _date(row.get("entry_date"))
    exit_date = _date(row.get("exit_date"))
    entry = _num(row.get("entry_price") or row.get("entry_limit"))
    exit_price = _num(row.get("exit_price"))
    qty = _num(row.get("position_quantity") or row.get("quantity"))
    points = _num(row.get("pnl_points"))
    if entry is None or entry_date is None:
        return None
    capital = round(entry * qty, 2) if qty is not None else None
    gross = round(points * qty, 2) if points is not None and qty is not None else None
    charges = None
    if gross is not None and exit_price is not None and exit_date is not None and qty is not None:
        charges = _charges(row, qty, entry, exit_price, exit_date)
    net = round(gross - charges["total"], 2) if gross is not None and charges else None
    status = str(row.get("classification") or row.get("position_status") or "UNKNOWN").upper()
    return {
        "strategy": strategy, "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"), "instrument_type": row.get("instrument_type"),
        "option_type": row.get("option_type"), "strike": row.get("strike"),
        "expiry": _date(row.get("expiry")), "signal_date": _date(row.get("signal_date")),
        "entry_date": entry_date, "entry_price": entry, "quantity": qty,
        "capital_deployed": capital, "exit_date": exit_date, "exit_price": exit_price,
        "classification": status, "pnl_points": points,
        "exit_reason": row.get("exit_reason"),
        "gross_pnl": gross, "charges": charges, "net_pnl": net,
        "pnl_status": ("REALIZED" if gross is not None and exit_date else
                       "OPEN_UNREALIZED" if status in ("NEW", "HOLD", "OPEN") else
                       "PENDING_VERIFICATION"),
        "capital_status": "KNOWN" if capital is not None else "QUANTITY_REQUIRED",
        "source": "VERIFIED_REPLAY_OR_LEDGER",
    }


def build_pnl_calendar(strategy_views: dict[str, Any], *, year: int | None = None,
                       month: int | None = None) -> dict[str, Any]:
    """Aggregate distinct strategy backtests; physical-delivery view is excluded."""
    selected: list[dict[str, Any]] = []
    sources = (("EXPIRY78", "EXPIRY78"), ("ORIGINAL366", "RECOVERED"))
    seen: set[tuple] = set()
    for strategy, group_name in sources:
        view = strategy_views.get(strategy) or {}
        groups = view.get("groups") if isinstance(view.get("groups"), dict) else {}
        for group in groups.values():
            if not isinstance(group, list):
                continue
            for row in group:
                if not isinstance(row, dict):
                    continue
                item = _trade_record(row, strategy)
                if not item:
                    continue
                key = (strategy, item.get("signal_id"), item["entry_date"],
                       item.get("signal_date"), item.get("exit_date"))
                if key in seen:
                    continue
                seen.add(key)
                # RECOVERED is the alternative model from the ORIGINAL366 entry,
                # not an additional live order. Label it as a separate simulation.
                if strategy == "ORIGINAL366":
                    item["strategy"] = "RECOVERED"
                    item["accounting_basis"] = "RETROSPECTIVE_ALTERNATIVE_MODEL_NOT_NEW_ORDER"
                else:
                    item["accounting_basis"] = "EXPIRY78_REPLAY"
                selected.append(item)

    def blank():
        return {"trade_count": 0, "realized_trade_count": 0, "gross_pnl": 0.0,
                "estimated_or_actual_charges": 0.0, "net_pnl": 0.0,
                "capital_deployed": 0.0, "capital_records": 0,
                "capital_missing_quantity": 0, "charges_estimated_count": 0,
                "charges_actual_count": 0, "net_pending_count": 0, "entries_count": 0, "peak_concurrent_capital": 0.0, "trades": []}

    days: dict[str, dict] = defaultdict(blank)
    months: dict[str, dict] = defaultdict(blank)
    totals = {"overall": blank(), "EXPIRY78": blank(), "RECOVERED": blank()}
    for trade in selected:
        strategy = trade["strategy"]
        exit_day = trade.get("exit_date")
        entry_day = trade["entry_date"]
        for bucket in (totals["overall"], totals[strategy]):
            bucket["trade_count"] += 1
            if trade.get("capital_deployed") is not None:
                bucket["capital_deployed"] += trade["capital_deployed"]
                bucket["capital_records"] += 1
            else:
                bucket["capital_missing_quantity"] += 1
            if trade.get("gross_pnl") is not None and exit_day:
                bucket["realized_trade_count"] += 1
                bucket["gross_pnl"] += trade["gross_pnl"]
                if trade.get("net_pnl") is not None:
                    bucket["net_pnl"] += trade["net_pnl"]
                else:
                    bucket["net_pending_count"] += 1
                if trade.get("charges"):
                    bucket["estimated_or_actual_charges"] += trade["charges"]["total"]
                    if trade["charges"]["basis"].startswith("ESTIMATED"):
                        bucket["charges_estimated_count"] += 1
                    else:
                        bucket["charges_actual_count"] += 1
        if exit_day:
            exit_bucket = days[exit_day]
            exit_bucket["trade_count"] += 1
            exit_bucket["realized_trade_count"] += int(trade.get("gross_pnl") is not None)
            exit_bucket["gross_pnl"] += trade.get("gross_pnl") or 0.0
            exit_bucket["estimated_or_actual_charges"] += (trade.get("charges") or {}).get("total", 0.0)
            if trade.get("net_pnl") is not None:
                exit_bucket["net_pnl"] += trade["net_pnl"]
            else:
                exit_bucket["net_pending_count"] += 1
            exit_bucket["trades"].append(trade)
            month_exit = months[exit_day[:7]]
            month_exit["trade_count"] += 1
            month_exit["realized_trade_count"] += int(trade.get("gross_pnl") is not None)
            month_exit["gross_pnl"] += trade.get("gross_pnl") or 0.0
            month_exit["estimated_or_actual_charges"] += (trade.get("charges") or {}).get("total", 0.0)
            if trade.get("net_pnl") is not None:
                month_exit["net_pnl"] += trade["net_pnl"]
            else:
                month_exit["net_pending_count"] += 1
            month_exit["trades"].append(trade)
        # Capital is allocated on entry date, not exit date.
        entry_bucket = days[entry_day]
        entry_bucket["capital_deployed"] += trade.get("capital_deployed") or 0.0
        entry_bucket["capital_records"] += int(trade.get("capital_deployed") is not None)
        entry_bucket["entries_count"] += 1
        if trade not in entry_bucket["trades"]:
            entry_bucket["trades"].append(trade)
        month_bucket = months[entry_day[:7]]
        month_bucket["capital_deployed"] += trade.get("capital_deployed") or 0.0
        month_bucket["capital_records"] += int(trade.get("capital_deployed") is not None)
        month_bucket["entries_count"] += 1
        if trade not in month_bucket["trades"]:
            month_bucket["trades"].append(trade)

    # Peak concurrent deployed capital uses entry-to-exit intervals.
    for strategy_name, bucket in totals.items():
        portfolio = selected if strategy_name == "overall" else [t for t in selected if t["strategy"] == strategy_name]
        events: dict[str, float] = defaultdict(float)
        for trade in portfolio:
            capital = trade.get("capital_deployed")
            if capital is None:
                continue
            events[trade["entry_date"]] += capital
            if trade.get("exit_date"):
                events[trade["exit_date"]] -= capital
        running = peak = 0.0
        for event_day in sorted(events):
            running += events[event_day]
            peak = max(peak, running)
        bucket["peak_concurrent_capital"] = round(peak, 2)
    for bucket in [*totals.values(), *days.values(), *months.values()]:
        for key in ("gross_pnl", "estimated_or_actual_charges", "net_pnl", "capital_deployed"):
            bucket[key] = round(bucket[key], 2)
    day_items = []
    for day, bucket in sorted(days.items()):
        if year is not None and int(day[:4]) != year:
            continue
        if month is not None and int(day[5:7]) != month:
            continue
        day_items.append({"date": day, **bucket})
    month_items = [{"month": key, **value} for key, value in sorted(months.items())
                   if (year is None or int(key[:4]) == year)]
    return {
        "currency": "INR", "year": year, "month": month,
        "summary": totals,
        "days": day_items, "months": month_items,
        "trades": selected,
        "charge_model": {
            "basis": "Indicative NSE equity-options model; broker-specific tariff/actual contract note overrides estimate",
            "rates": dict(RATES),
            "notes": ["Brokerage assumed ₹20 per executed order (buy + sell = ₹40)",
                      "STT sell side: 0.10% before 01-Apr-2026; 0.15% from 01-Apr-2026; exercise STT 0.125% / 0.15% on intrinsic value",
                      "Expiry exercise estimate uses one executed entry order; brokerage is not assumed on exercise/assignment",
                      "NSE options exchange charges estimated at 0.03553% of premium turnover",
                      "Stamp duty estimated 0.003% on buy premium; SEBI fee ₹10/crore; GST 18% on brokerage, exchange and SEBI fees",
                      "Physical delivery taxes, exercise/assignment charges and broker-specific levies require contract-note reconciliation",
                      "Unknown quantity or exit valuation is not fabricated; corresponding rupee P&L remains pending"],
        },
        "accounting_note": "RECOVERED is a retrospective ORIGINAL366 alternative-exit simulation, not an additional broker position. Physical-settlement rows are excluded from overall P&L to prevent double counting.",
    }
