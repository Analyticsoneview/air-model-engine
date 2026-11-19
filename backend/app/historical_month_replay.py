"""Point-in-time EXPIRY78 replay over retained NSE FO daily evidence.

The selected month can refer to signal month or contract expiry month. The same
canonical EXPIRY78 evaluator is used in either mode. Unsupported strategies are
reported explicitly; daily bars are never substituted for intraday or option-chain
evidence.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.model_engine_expiry78 import ENGINE_VERSION as EXPIRY78_ENGINE_VERSION, evaluate_expiry78_contract
from app.nse_bhavcopy import _get_store, nse_data_status


STRATEGY_LIMITATIONS = {
    "ORIGINAL366": "Requires preserved historical cohort membership and verified daily option evidence plus its dedicated strategy evaluator.",
    "RECOVERY": "Requires verified recovery qualification evidence and its dedicated strategy evaluator.",
    "EXPIRYSCAN": "Requires archived point-in-time option-chain snapshots including bid/ask, volume and OI; daily bhavcopy is not a valid substitute.",
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
    after = date(first.year + (first.month == 12), 1 if first.month == 12 else first.month + 1, 1)
    return first, date.fromordinal(after.toordinal() - 1)


def _valid_mark(bar: dict[str, Any]) -> bool:
    try:
        op, high, low, close, quantity = (
            float(bar[key]) for key in ("open", "high", "low", "close", "quantity")
        )
    except (TypeError, ValueError, KeyError):
        return False
    return (min(op, high, low, close, quantity) > 0
            and high >= max(op, close, low) and low <= min(op, close))


def replay_expiry78_month(rows: list[dict[str, Any]], *, month: str,
                          as_of: str, basis: str = "expiry") -> dict[str, Any]:
    """Replay EXPIRY78 for signals or expiries in a selected calendar month."""
    first, last = _month_bounds(month)
    if basis not in {"expiry", "signal"}:
        raise ValueError("basis must be 'expiry' or 'signal'")
    as_of_day = date.fromisoformat(as_of)
    grouped: dict[tuple[str, str, float, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            expiry = date.fromisoformat(str(row.get("expiry"))[:10])
            trade_day = date.fromisoformat(str(row.get("trade_date"))[:10])
        except (TypeError, ValueError):
            continue
        option_type = str(row.get("option_type") or "").upper()
        strike = row.get("strike")
        month_match = first <= expiry <= last if basis == "expiry" else first <= trade_day <= last or expiry >= first
        if not month_match or trade_day > as_of_day:
            continue
        if option_type not in {"CE", "PE"} or strike is None:
            continue
        instrument_type = str(row.get("instrument_type") or "").upper()
        key = (str(row.get("symbol") or "").upper(), expiry.isoformat(),
               float(strike), option_type, instrument_type)
        grouped[key].append(row)

    trades: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    for (symbol, expiry, strike, option_type, instrument_type), raw_bars in sorted(grouped.items()):
        raw_bars.sort(key=lambda item: str(item.get("trade_date") or ""))
        daily_bars = [{
            "date": str(row.get("trade_date"))[:10],
            "open": row.get("open"), "high": row.get("high"),
            "low": row.get("low"), "close": row.get("close"),
            "quantity": row.get("volume"),
            "underlying_close": row.get("underlying_price"),
        } for row in raw_bars]
        evaluated = evaluate_expiry78_contract({
            "symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "instrument_type": instrument_type,
            "evidence": {"daily_option_bars": daily_bars},
        }, as_of=as_of)
        month_trades = [
            item for item in evaluated.get("trades", [])
            if (first <= date.fromisoformat(item.get("signal_date", "")) <= last
                if basis == "signal"
                else first <= date.fromisoformat(expiry) <= last)
        ]
        if not month_trades:
            continue
        expiry_day = date.fromisoformat(expiry)
        valid_marks = [
            bar for bar in daily_bars
            if _valid_mark(bar)
            and date.fromisoformat(bar["date"]) <= min(expiry_day, as_of_day)
        ]
        contract_trade_count = 0
        for item in month_trades:
            status = item.get("position_status")
            # Closed trades are valued at their own exit, never at a later
            # contract close. Open/unresolved trades use the latest retained
            # EOD close up to report as-of and contract expiry.
            if status == "EXITED":
                latest_price = item.get("exit_price")
                latest_price_date = item.get("exit_date")
            elif status == "EXPIRY_SURVIVOR":
                latest_price = item.get("intrinsic_value")
                latest_price_date = item.get("exit_date")
            else:
                mark = valid_marks[-1] if valid_marks else None
                latest_price = mark.get("close") if mark else None
                latest_price_date = mark.get("date") if mark else None
            item["latest_price"] = latest_price
            item["latest_price_date"] = latest_price_date
            try:
                entry_day = date.fromisoformat(item["entry_date"])
                item["days_to_expiry"] = (expiry_day - entry_day).days
            except (TypeError, ValueError, KeyError):
                item["days_to_expiry"] = None
            if status in {"EXITED", "EXPIRY_SURVIVOR"}:
                item["current_pnl_points"] = item.get("pnl_points")
            elif latest_price is not None and item.get("entry_price") is not None:
                item["current_pnl_points"] = round(float(latest_price) - float(item["entry_price"]), 4)
            else:
                item["current_pnl_points"] = None
            item["mark_to_market_pnl_points"] = (
                round(float(latest_price) - float(item["entry_price"]), 4)
                if latest_price is not None and item.get("entry_price") is not None else None
            )
            item["current_pnl_rupees"] = item.get("net_pnl_rupees")
            item["lot_size"] = raw_bars[-1].get("lot_size")
            item["entry_fill_basis"] = "MODELLED_DAILY_LOW_TOUCH_NOT_BROKER_EXECUTION"
            item["classification_label"] = {
                "SL": "SL HIT", "EXPIRED": "EXPIRY SURVIVOR",
                "HOLD": "HOLD / CARRY-FORWARD", "NEW": "NEW",
                "WAIT": "WAIT", "UNRESOLVED": "UNRESOLVED",
            }.get(item.get("classification"), item.get("classification"))
            trades.append({"strategy": "EXPIRY78", **item})
            contract_trade_count += 1
        contracts.append({
            "symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "instrument_type": instrument_type,
            "observations": len(daily_bars),
            "data_quality": evaluated.get("data_quality"),
            "trade_count": contract_trade_count,
        })

    trades.sort(key=lambda item: (item.get("signal_date", ""),
                                  item.get("symbol", ""), item.get("expiry", ""),
                                  item.get("strike", 0), item.get("option_type", "")))
    counts = {label: sum(item.get("classification") == label for item in trades)
              for label in ("NEW", "HOLD", "SL", "EXPIRED", "WAIT", "UNRESOLVED")}
    return {
        "strategy": "EXPIRY78", "strategy_version": EXPIRY78_ENGINE_VERSION,
        "status": "COMPLETED",
        "month": month, "month_basis": basis,
        "signal_month": month if basis == "signal" else None,
        "expiry_month": month if basis == "expiry" else None,
        "as_of": as_of,
        "contracts_examined": len(grouped),
        "contracts_with_qualifying_entries": len(contracts),
        "trade_count": len(trades), "classification_counts": counts,
        "contracts": contracts, "trades": trades,
        "rules": "Canonical EXPIRY78 evaluator; daily option OHLCV only.",
    }


def historical_month_report(*, month: str, strategies: list[str],
                             basis: str = "expiry") -> dict[str, Any]:
    """Build a selected signal-month or expiry-month report from retained FO rows."""
    first, last = _month_bounds(month)
    if basis not in {"expiry", "signal"}:
        raise ValueError("basis must be 'expiry' or 'signal'")
    status = nse_data_status()
    fo = status.get("markets", {}).get("FO", {})
    earliest, latest = fo.get("first_date"), fo.get("last_date")
    if not earliest or not latest:
        return {"status": "DATA_UNAVAILABLE", "month": month, "month_basis": basis,
                "available_data": {"first_date": earliest, "last_date": latest},
                "strategies": [], "note": "No imported NSE FO daily records are available."}
    if last.isoformat() < earliest or (basis == "signal" and first.isoformat() > latest):
        return {"status": "OUTSIDE_RETENTION_WINDOW", "month": month, "month_basis": basis,
                "available_data": {"first_date": earliest, "last_date": latest},
                "strategies": [], "note": "Selected signal period is outside retained NSE FO daily records."}

    store = _get_store()
    expiry_filter = "expiry>=?" if basis == "signal" else "expiry>=? AND expiry<=?"
    params = (first.isoformat(), latest) if basis == "signal" else (first.isoformat(), last.isoformat(), latest)
    where = f"market='FO' AND {expiry_filter} AND trade_date<=? AND option_type IN ('CE','PE')"
    with store._db() as db:
        rows = db.execute(f"""
            SELECT trade_date, symbol, instrument_type, expiry, strike,
                   option_type, open, high, low, close, volume,
                   underlying_price, lot_size
            FROM nse_bhavcopy WHERE {where}
            ORDER BY symbol, expiry, strike, option_type, trade_date
        """, params).fetchall()
    normalized_rows = [dict(row) for row in rows]
    if basis == "expiry" and first.isoformat() > latest and not normalized_rows:
        return {
            "status": "CONTRACTS_NOT_IN_RETAINED_DATA",
            "mode": "HISTORICAL_EXPIRY_MONTH",
            "month": month, "month_basis": basis, "expiry_month": month,
            "period": {"start_date": first.isoformat(), "end_date": last.isoformat()},
            "data_available": {"first_date": earliest, "last_date": latest},
            "source": "Retained NSE FO EOD bhavcopy", "source_rows": 0,
            "strategies": [], "note": "No option-contract rows for this future expiry month are present in the retained NSE FO data yet.",
        }
    selected = {str(item).strip().upper() for item in strategies if str(item).strip()}
    if not selected:
        selected = {"EXPIRY78"}
    results = []
    if "EXPIRY78" in selected:
        results.append(replay_expiry78_month(normalized_rows, month=month, as_of=latest, basis=basis))
    for strategy in sorted(selected - {"EXPIRY78"}):
        results.append({"strategy": strategy, "status": "NOT_REPLAYED",
                        "reason": STRATEGY_LIMITATIONS.get(strategy,
                            "Strategy is not registered for this historical evidence replay."),
                        "trade_count": 0, "trades": []})
    return {
        "status": "COMPLETED_WITH_LIMITATIONS" if any(item["status"] == "NOT_REPLAYED" for item in results) else "COMPLETED",
        "mode": "HISTORICAL_SIGNAL_MONTH" if basis == "signal" else "HISTORICAL_EXPIRY_MONTH",
        "month": month, "month_basis": basis,
        "signal_month": month if basis == "signal" else None,
        "expiry_month": month if basis == "expiry" else None,
        "period": {"start_date": first.isoformat(), "end_date": last.isoformat()},
        "data_available": {"first_date": earliest, "last_date": latest},
        "source": "Retained NSE FO EOD bhavcopy", "source_rows": len(normalized_rows),
        "strategy_versions": {"EXPIRY78": EXPIRY78_ENGINE_VERSION},
        "selected_strategies": sorted(selected), "strategies": results,
        "limitations": [
            "Signal-month mode includes contracts expiring in that month or later; expiry-month mode includes contracts expiring in the selected month.",
            "Signal-month replay uses the same canonical evaluator but is constrained by the retained historical data window.",
            "Only EXPIRY78 is currently connected to this daily-OHLCV replay; other strategies remain NOT_REPLAYED until their own evidence and canonical evaluators are available.",
            "Daily bars cannot establish intraday fill/stop ordering; ambiguous same-session entry/stop cases are UNRESOLVED.",
            "Historical replay is research-only and never places broker orders.",
        ],
    }
