"""Month-selected historical replay over retained NSE FO bhavcopy evidence.

This first gate replays EXPIRY78 from daily option OHLCV. Other strategies are
reported with explicit evidence/engine availability; daily bars are never
substituted for intraday ticks or historical bid/ask snapshots.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.model_engine_expiry78 import evaluate_expiry78_contract
from app.nse_bhavcopy import _get_store, nse_data_status


STRATEGY_LIMITATIONS = {
    "ORIGINAL366": "Requires its preserved historical cohort membership and verified daily option evidence; generalized month replay is not yet wired.",
    "RECOVERY": "Requires explicit verified recovery evidence and its dedicated executor; generic option bars alone cannot establish recovery qualification.",
    "EXPIRYSCAN": "Requires archived point-in-time option-chain snapshots including bid/ask, volume and OI. Daily bhavcopy is not a valid substitute.",
    "ORB_MORNING": "Requires timestamped intraday candles/ticks for the 09:18–09:23 opening range and subsequent confirmation.",
    "ORB_AFTERNOON": "Requires timestamped intraday candles/ticks for the 12:57–13:00 opening range and subsequent confirmation.",
}


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM format") from exc
    if len(month) != 7 or month[4] != "-":
        raise ValueError("month must use YYYY-MM format")
    if first.month == 12:
        after = date(first.year + 1, 1, 1)
    else:
        after = date(first.year, first.month + 1, 1)
    return first, date.fromordinal(after.toordinal() - 1)


def replay_expiry78_month(rows: list[dict[str, Any]], *, month: str,
                          as_of: str) -> dict[str, Any]:
    """Replay every retained FO option contract expiring in the selected month."""
    first, last = _month_bounds(month)
    grouped: dict[tuple[str, str, float, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            expiry = date.fromisoformat(str(row.get("expiry"))[:10])
            trade_day = date.fromisoformat(str(row.get("trade_date"))[:10])
        except (TypeError, ValueError):
            continue
        option_type = str(row.get("option_type") or "").upper()
        strike = row.get("strike")
        if not (first <= expiry <= last) or trade_day > date.fromisoformat(as_of):
            continue
        if option_type not in {"CE", "PE"} or strike is None:
            continue
        instrument_type = str(row.get("instrument_type") or "").upper()
        key = (str(row.get("symbol") or "").upper(), expiry.isoformat(),
               float(strike), option_type, instrument_type)
        grouped[key].append(row)

    contracts = []
    trades = []
    for (symbol, expiry, strike, option_type, instrument_type), raw_bars in sorted(grouped.items()):
        raw_bars.sort(key=lambda item: str(item.get("trade_date") or ""))
        daily_bars = []
        for row in raw_bars:
            daily_bars.append({
                "date": str(row.get("trade_date"))[:10],
                "open": row.get("open"), "high": row.get("high"),
                "low": row.get("low"), "close": row.get("close"),
                "quantity": row.get("volume"),
                # NSE FO bhavcopy carries the underlying reference price for
                # that session. Only the expiry-session value is used for
                # intrinsic settlement by EXPIRY78.
                "underlying_close": row.get("underlying_price"),
            })
        contract = {
            "symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "instrument_type": instrument_type,
            "evidence": {"daily_option_bars": daily_bars},
        }
        evaluated = evaluate_expiry78_contract(contract, as_of=as_of)
        # Latest mark is the last valid retained EOD option close on/before
        # expiry and the report as-of date. It is not an intraday executable quote.
        valid_mark_bars = []
        for bar in daily_bars:
            try:
                op, high, low, close, quantity = (
                    float(bar[key]) for key in ("open", "high", "low", "close", "quantity")
                )
            except (TypeError, ValueError, KeyError):
                continue
            if (min(op, high, low, close, quantity) > 0
                    and high >= max(op, close, low)
                    and low <= min(op, close)):
                valid_mark_bars.append(bar)
        latest_mark = valid_mark_bars[-1] if valid_mark_bars else None
        expiry_day = date.fromisoformat(expiry)
        as_of_day = date.fromisoformat(as_of)
        days_to_expiry = (expiry_day - as_of_day).days
        month_trades = [item for item in evaluated.get("trades", [])
                        if first.isoformat() <= item.get("signal_date", "") <= last.isoformat()]
        for item in month_trades:
            item["latest_price"] = latest_mark.get("close") if latest_mark else None
            item["latest_price_date"] = latest_mark.get("date") if latest_mark else None
            item["days_to_expiry"] = days_to_expiry
            mark_pnl = (
                round(float(latest_mark["close"]) - float(item["entry_price"]), 4)
                if latest_mark and item.get("entry_price") is not None else None
            )
            item["mark_to_market_pnl_points"] = mark_pnl
            item["current_pnl_points"] = (
                item.get("pnl_points") if item.get("position_status") != "OPEN"
                else mark_pnl
            )
            # Position quantity and charges are not supplied by NSE bhavcopy.
            item["current_pnl_rupees"] = None
            item["lot_size"] = raw_bars[-1].get("lot_size")
        if month_trades:
            contracts.append({
                "symbol": symbol, "expiry": expiry, "strike": strike,
                "option_type": option_type, "instrument_type": instrument_type,
                "observations": len(daily_bars),
                "data_quality": evaluated.get("data_quality"),
                "trade_count": len(month_trades),
            })
            for item in month_trades:
                trades.append({"strategy": "EXPIRY78", **item})

    trades.sort(key=lambda item: (item.get("signal_date", ""),
                                  item.get("symbol", ""),
                                  item.get("expiry", ""),
                                  item.get("strike", 0),
                                  item.get("option_type", "")))
    return {
        "strategy": "EXPIRY78",
        "status": "COMPLETED",
        "expiry_month": month,
        "as_of": as_of,
        "contracts_examined": len(grouped),
        "contracts_with_qualifying_entries": len(contracts),
        "trade_count": len(trades),
        "classification_counts": {
            label: sum(item.get("classification") == label for item in trades)
            for label in ("NEW", "HOLD", "SL", "EXPIRED", "WAIT")
        },
        "contracts": contracts,
        "trades": trades,
        "rules": "Existing EXPIRY78 seven-rule evaluator; daily option OHLCV only.",
    }


def historical_month_report(*, month: str, strategies: list[str]) -> dict[str, Any]:
    """Build a selected-expiry-month report from retained NSE FO records."""
    first, last = _month_bounds(month)
    status = nse_data_status()
    fo = status.get("markets", {}).get("FO", {})
    earliest = fo.get("first_date")
    latest = fo.get("last_date")
    if not earliest or not latest:
        return {
            "status": "DATA_UNAVAILABLE", "expiry_month": month,
            "available_data": {"first_date": earliest, "last_date": latest},
            "strategies": [], "note": "No imported NSE FO daily records are available.",
        }
    if last.isoformat() < earliest or first.isoformat() > latest:
        return {
            "status": "OUTSIDE_RETENTION_WINDOW", "expiry_month": month,
            "available_data": {"first_date": earliest, "last_date": latest},
            "strategies": [], "note": "Selected expiry month is outside retained NSE FO daily records.",
        }

    # Include all retained daily bars through the latest imported session so
    # contracts expiring in the selected month can be valued at expiry.
    store = _get_store()
    with store._db() as db:
        rows = db.execute("""
            SELECT trade_date, symbol, instrument_type, expiry, strike,
                   option_type, open, high, low, close, volume,
                   underlying_price, lot_size
            FROM nse_bhavcopy
            WHERE market='FO' AND expiry>=? AND expiry<=? AND trade_date<=?
              AND option_type IN ('CE','PE')
            ORDER BY symbol, expiry, strike, option_type, trade_date
        """, (first.isoformat(), last.isoformat(), latest)).fetchall()
    normalized_rows = [dict(row) for row in rows]

    selected = {str(item).strip().upper() for item in strategies if str(item).strip()}
    if not selected:
        selected = {"EXPIRY78"}
    results = []
    if "EXPIRY78" in selected:
        results.append(replay_expiry78_month(normalized_rows, month=month, as_of=latest))
    for strategy in sorted(selected - {"EXPIRY78"}):
        results.append({
            "strategy": strategy,
            "status": "NOT_REPLAYED",
            "reason": STRATEGY_LIMITATIONS.get(
                strategy, "Strategy is not registered for this historical daily-option replay."
            ),
            "trade_count": 0,
            "trades": [],
        })
    return {
        "status": "COMPLETED_WITH_LIMITATIONS" if any(
            item["status"] == "NOT_REPLAYED" for item in results
        ) else "COMPLETED",
        "mode": "HISTORICAL_EXPIRY_MONTH",
        "expiry_month": month,
        "period": {"start_date": first.isoformat(), "end_date": last.isoformat()},
        "data_available": {"first_date": earliest, "last_date": latest},
        "source": "Retained NSE FO EOD bhavcopy",
        "source_rows": len(normalized_rows),
        "selected_strategies": sorted(selected),
        "strategies": results,
        "limitations": [
            "Only contracts whose expiry falls in the selected month are included.",
            "EXPIRY78 uses the existing daily OHLCV evaluator; no intraday execution price is inferred.",
            "Other strategies are explicitly marked NOT_REPLAYED until their required historical evidence and engines are connected.",
            "Historical replay is research-only and never places broker orders.",
        ],
    }
