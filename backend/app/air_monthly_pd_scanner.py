"""AIR MPDSM historical EOD universe scanner.

Scans the versioned Nifty 100/Midcap 150/Smallcap 250 registry using only
completed NSE CM/FO bhavcopy rows. Stock qualification is evaluated first;
options are evaluated separately and cannot promote a rejected stock.
"""
from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Any

from app.air_monthly_pd import (
    classify_price_structure, classify_premium_discount, current_month_extremes,
    evaluate_current_month_low_acceptance, evaluate_resistance_rejection,
    evaluate_support_acceptance, monthly_levels, monthly_reference_session,
)
from app.nse_bhavcopy import nse_data_rows, _get_store
from app.nse_index_universe import NSEIndexUniverseStore


def _calendar_sessions(store, year: int) -> dict[str, str]:
    calendar = store.get_meta(f"trading_calendar_{year}") or {}
    holidays = {x["date"] for x in calendar.get("segments", {}).get("CM", [])}
    sessions = {}
    from datetime import timedelta
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    day = start
    while day <= end:
        if day.weekday() < 5:
            sessions[day.isoformat()] = "HOLIDAY" if day.isoformat() in holidays else "TRADING_DAY"
        day += timedelta(days=1)
    return sessions


def _coverage(symbol: str, bars: list[dict[str, Any]], expected_dates: list[str]) -> dict[str, Any]:
    actual = {str(row["trade_date"]) for row in bars}
    missing = [day for day in expected_dates if day not in actual]
    ratio = len(actual.intersection(expected_dates)) / max(1, len(expected_dates))
    return {"status": "READY" if ratio >= 0.90 and len(bars) >= 12 else "DATA_INSUFFICIENT",
            "symbol": symbol, "expected_sessions": len(expected_dates),
            "observed_sessions": len(actual.intersection(expected_dates)),
            "coverage_pct": round(ratio * 100, 2), "missing_sessions": missing[:30]}


def _bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"date": r["trade_date"], "open": r.get("open"), "high": r.get("high"),
             "low": r.get("low"), "close": r.get("close"), "volume": r.get("volume")}
            for r in sorted(rows, key=lambda x: x["trade_date"]) if r.get("high") is not None
            and r.get("low") is not None and r.get("close") is not None]


def _monthly_bar_groups(bars: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for bar in bars:
        groups.setdefault(str(bar["date"])[:7], []).append(bar)
    return groups


def _stock_record(symbol: str, memberships: list[str], raw_rows: list[dict[str, Any]],
                  as_of: str, expected_dates: list[str], sessions: dict[str, str]) -> dict[str, Any]:
    bars = _bars([r for r in raw_rows if str(r["trade_date"]) <= as_of])
    coverage = _coverage(symbol, bars, [d for d in expected_dates if d <= as_of])
    base = {"symbol": symbol, "index_memberships": memberships, "coverage": coverage}
    if coverage["status"] != "READY":
        return {**base, "qualification": "DATA_INSUFFICIENT", "reason": "Insufficient completed NSE CM history"}
    groups = _monthly_bar_groups(bars)
    asof_date = date.fromisoformat(as_of)
    cycle_month = asof_date.strftime("%Y-%m")
    previous_month = (asof_date.replace(day=1) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m")
    if previous_month not in groups or cycle_month not in groups:
        return {**base, "qualification": "DATA_INSUFFICIENT", "reason": "Previous/current month bars missing"}
    try:
        reference = monthly_reference_session(asof_date.year, asof_date.month, sessions)
        previous = groups[previous_month]
        levels = monthly_levels(previous)
        current_to_reference = [b for b in groups[cycle_month] if b["date"] <= reference.isoformat()]
        if not current_to_reference:
            return {**base, "qualification": "DATA_INSUFFICIENT", "reason": "Reference-session bars missing"}
        extremes = current_month_extremes(current_to_reference, reference_date=reference.isoformat(),
                                           pml=levels["pml"], pmh=levels["pmh"])
        after = [b for b in bars if b["date"] > reference.isoformat()]
        support = evaluate_support_acceptance(after, levels["pml"], 2, reference.isoformat())
        ml = (evaluate_current_month_low_acceptance(after, extremes["cml"], 2, reference.isoformat())
              if extremes.get("ml_candidate") else {"status": "NOT_APPLICABLE"})
        mh = (evaluate_resistance_rejection(after, extremes["cmh"], 2, reference.isoformat())
              if extremes.get("mh_candidate") else {"status": "NOT_APPLICABLE"})
        last = bars[-1]
        pattern = classify_price_structure(bars[-90:])
        zone = classify_premium_discount(float(last["close"]), levels["pml"], levels["pmh"])
        qualified = support["status"] == "OPEN_FOR_BUY" or ml.get("status") == "ML_CONFIRMED"
        return {**base, "cycle_month": cycle_month, "reference_date": reference.isoformat(),
                "levels": levels, "current_month_extremes": extremes, "support": support,
                "ml_acceptance": ml, "mh_rejection": mh, "pattern": pattern,
                "premium_discount": zone, "last_close": last["close"],
                "qualification": "QUALIFIED" if qualified else
                    "INVALIDATED" if support["status"] == "INVALIDATED" else
                    "WATCH" if support["status"] == "WAITING" else "NOT_QUALIFIED",
                "as_of_date": as_of}
    except (ValueError, KeyError, TypeError) as exc:
        return {**base, "qualification": "DATA_INSUFFICIENT", "reason": str(exc)}


def scan_monthly_pd_universe(as_of_date: str | None = None) -> dict[str, Any]:
    """Scan equity constituents first, then contracts for qualified underlyings."""
    nse_store = _get_store()
    latest = nse_store.status().get("markets", {}).get("CM", {}).get("last_date")
    as_of = min(as_of_date or latest or "", latest or as_of_date or "")
    if not as_of:
        return {"status": "DATA_INSUFFICIENT", "reason": "No NSE CM EOD sessions imported"}
    registry = NSEIndexUniverseStore(nse_store.path).latest_universe()
    if registry.get("status") != "READY":
        return {"status": "DATA_INSUFFICIENT", "reason": "Official index constituent registry unavailable",
                "universe": registry}
    calendar = nse_store.get_meta(f"trading_calendar_{date.fromisoformat(as_of).year}") or {}
    if not calendar:
        return {"status": "DATA_INSUFFICIENT", "reason": "Official NSE CM trading calendar unavailable"}
    sessions = _calendar_sessions(nse_store, date.fromisoformat(as_of).year)
    start_month = (date.fromisoformat(as_of).replace(day=1) - __import__("datetime").timedelta(days=90)).strftime("%Y-%m-%d")
    all_rows = nse_data_rows("CM", start_date=start_month, end_date=as_of, limit=5000)
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in all_rows:
        by_symbol.setdefault(row["symbol"], []).append(row)
    expected = [d for d, status in sessions.items() if status == "TRADING_DAY" and start_month <= d <= as_of]
    stocks = []
    for item in registry["constituents"]:
        stocks.append(_stock_record(item["symbol"], item["index_memberships"],
                                    by_symbol.get(item["symbol"], []), as_of, expected, sessions))
    qualified_symbols = {x["symbol"] for x in stocks if x["qualification"] == "QUALIFIED"}
    fo_rows = nse_data_rows("FO", start_date=start_month, end_date=as_of, limit=5000)
    contracts: dict[tuple, list[dict[str, Any]]] = {}
    for row in fo_rows:
        if row["symbol"] in qualified_symbols and row.get("option_type") in {"CE", "PE"}:
            key = (row["symbol"], row.get("expiry"), row.get("strike"), row.get("option_type"))
            contracts.setdefault(key, []).append(row)
    options = []
    for (symbol, expiry, strike, option_type), rows in contracts.items():
        rows.sort(key=lambda x: x["trade_date"])
        last = rows[-1]
        closes = [float(x["close"]) for x in rows if x.get("close") is not None]
        vols = [float(x["volume"]) for x in rows if x.get("volume") is not None]
        oi_changes = [float(x["oi_change"]) for x in rows if x.get("oi_change") is not None]
        spot = float(last.get("underlying_price") or 0)
        itm = bool(spot and strike is not None and
                   ((option_type == "CE" and float(strike) < spot) or
                    (option_type == "PE" and float(strike) > spot)))
        options.append({"symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "premium_close": last.get("close"),
            "premium_change_pct": round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) > 1 and closes[-2] else None,
            "volume": last.get("volume"), "volume_avg": round(mean(vols[:-1]), 2) if len(vols) > 1 else None,
            "open_interest": last.get("open_interest"), "oi_change": last.get("oi_change"),
            "oi_change_pct": round(oi_changes[-1] / max(1, abs(float(last.get("open_interest") or 0) - oi_changes[-1])) * 100, 2) if oi_changes else None,
            "spot": spot or None, "moneyness": "ITM" if itm else "OTM_OR_ATM",
            "days_to_expiry": (date.fromisoformat(expiry) - date.fromisoformat(as_of)).days if expiry else None,
            "bid_ask_spread": "DATA_INSUFFICIENT", "liquidity": "EOD_VOLUME_ONLY",
            "qualification": "WATCH" if last.get("close") is not None and last.get("volume") else "DATA_INSUFFICIENT",
            "qualification_note": "EOD data only; spread and intraday liquidity unavailable"})
    return {"status": "COMPLETED", "as_of_date": as_of, "timeframe": "DAILY_EOD",
        "universe": {"index_counts": registry["index_counts"],
                     "unique_symbol_count": registry["unique_symbol_count"]},
        "coverage": {"symbols": len(stocks),
                     "ready": sum(x["coverage"]["status"] == "READY" for x in stocks),
                     "insufficient": sum(x["coverage"]["status"] != "READY" for x in stocks)},
        "stock_results": stocks, "qualified_stock_symbols": sorted(qualified_symbols),
        "options_results": options,
        "options_disclosure": "Options are scanned only after stock qualification. EOD bhavcopy does not contain historical bid/ask; options are WATCH only until all required evidence is available.",
        "broker_orders_placed": False}
