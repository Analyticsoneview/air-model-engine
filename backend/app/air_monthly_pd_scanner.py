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
    classify_price_structure, evaluate_pattern_lifecycle, classify_premium_discount, current_month_extremes,
    evaluate_current_month_low_acceptance, evaluate_resistance_rejection,
    evaluate_support_acceptance, monthly_levels, monthly_reference_session,
)
from app.nse_bhavcopy import nse_data_rows_exact_symbol, _get_store
from app.air_monthly_pd_store import AirMonthlyPdStore
from app.nse_universe import NSEUniverseStore


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


def _calendar_sessions_for_range(store, start_date: date, end_date: date) -> dict[str, str]:
    """Build CM sessions across every calendar year touched by the scan window."""
    sessions: dict[str, str] = {}
    for year in range(start_date.year, end_date.year + 1):
        sessions.update(_calendar_sessions(store, year))
    return sessions


def _coverage(symbol: str, bars: list[dict[str, Any]], expected_dates: list[str]) -> dict[str, Any]:
    actual = {
        str(row.get("trade_date") or row.get("date"))
        for row in bars if row.get("trade_date") or row.get("date")
    }
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
        if reference > asof_date:
            return {
                **base, "qualification": "DATA_INSUFFICIENT",
                "reason": "Monthly reference session has not completed as of the requested scan date",
                "reference_date": reference.isoformat(),
            }
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
        pattern = evaluate_pattern_lifecycle(classify_price_structure(bars[-90:]), bars[-90:])
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


def classify_option_eod_evidence(*, premium_change_pct: float | None,
                                  volume: float | None, volume_avg: float | None,
                                  oi_change_pct: float | None) -> dict[str, Any]:
    """Classify EOD-only option activity without pretending bid/ask liquidity exists."""
    if premium_change_pct is None or volume is None or volume_avg is None or oi_change_pct is None:
        return {"qualification": "DATA_INSUFFICIENT", "evidence_score": None,
                "reason": "Premium, volume baseline and OI change are all required"}
    checks = {
        "premium_momentum": abs(float(premium_change_pct)) >= 5,
        "volume_expansion": float(volume_avg) > 0 and float(volume) / float(volume_avg) >= 1.5,
        "oi_confirmation": abs(float(oi_change_pct)) >= 5,
    }
    score = sum(checks.values())
    return {"qualification": "EOD_CANDIDATE" if score == 3 else "WATCH",
            "evidence_score": score, "evidence": checks,
            "reason": "EOD-only evidence; spread and intraday liquidity are unavailable",
            "strong_participation": False}


def scan_monthly_pd_universe(as_of_date: str | None = None) -> dict[str, Any]:
    """Scan equity constituents first, then contracts for qualified underlyings."""
    nse_store = _get_store()
    latest = nse_store.status().get("markets", {}).get("CM", {}).get("last_date")
    as_of = min(as_of_date or latest or "", latest or as_of_date or "")
    if not as_of:
        return {"status": "DATA_INSUFFICIENT", "reason": "No NSE CM EOD sessions imported"}
    registry = NSEUniverseStore().latest_universe()
    if registry.get("status") != "READY":
        return {"status": "DATA_INSUFFICIENT", "reason": "Official index constituent registry unavailable",
                "universe": registry}
    as_of_day = date.fromisoformat(as_of)
    start_day = as_of_day.replace(day=1) - __import__("datetime").timedelta(days=90)
    start_month = start_day.strftime("%Y-%m-%d")
    for year in range(start_day.year, as_of_day.year + 1):
        if not nse_store.get_meta(f"trading_calendar_{year}"):
            return {"status": "DATA_INSUFFICIENT",
                    "reason": f"Official NSE CM trading calendar unavailable for {year}"}
    sessions = _calendar_sessions_for_range(nse_store, start_day, as_of_day)
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    # Query per constituent: the underlying NSE query API caps each request at
    # 5,000 rows, which is ample per equity but not for the whole universe.
    for item in registry["constituents"]:
        symbol = item["symbol"]
        by_symbol[symbol] = nse_data_rows_exact_symbol("CM", symbol, start_date=start_month, end_date=as_of, limit=5000)
    expected = [d for d, status in sessions.items() if status == "TRADING_DAY" and start_month <= d <= as_of]
    stocks = []
    for item in registry["constituents"]:
        stocks.append(_stock_record(item["symbol"], item["index_memberships"],
                                    by_symbol.get(item["symbol"], []), as_of, expected, sessions))
    # Persist immutable per-symbol daily snapshots; duplicate refreshes are idempotent.
    persisted = 0
    pd_store = AirMonthlyPdStore()
    try:
        for stock in stocks:
            levels = stock.get("levels")
            reference_date = stock.get("reference_date")
            if not levels or not reference_date:
                continue
            cycle = pd_store.save_cycle(
                instrument_type="EQUITY", symbol=stock["symbol"],
                cycle_month=stock["cycle_month"], reference_date=reference_date,
                pml=levels["pml"], pmh=levels["pmh"], eq=levels["eq"])
            snapshot = pd_store.save_snapshot(
                cycle_id=cycle["cycle_id"], as_of_date=as_of,
                snapshot_type="DAILY_EOD", support_status=stock.get("qualification", "DATA_INSUFFICIENT"),
                pattern=(stock.get("pattern") or {}).get("pattern", "NONE"),
                pattern_state=(stock.get("pattern") or {}).get("state", "INCOMPLETE"),
                expiry_metadata={},
                evidence={"coverage": stock.get("coverage"), "support": stock.get("support"),
                          "current_month_extremes": stock.get("current_month_extremes"),
                          "ml_acceptance": stock.get("ml_acceptance"), "mh_rejection": stock.get("mh_rejection"),
                          "premium_discount": stock.get("premium_discount")},
                forecast={"pattern": stock.get("pattern"), "qualification": stock.get("qualification")},
                actual={"last_close": stock.get("last_close")})
            persisted += int(snapshot is not None)
    finally:
        pd_store.close()
    qualified_symbols = {x["symbol"] for x in stocks if x["qualification"] == "QUALIFIED"}
    fo_rows = []
    for symbol in sorted(qualified_symbols):
        fo_rows.extend(nse_data_rows_exact_symbol("FO", symbol, start_date=start_month, end_date=as_of, limit=5000))
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
        premium_change = round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) > 1 and closes[-2] else None
        volume_avg = round(mean(vols[:-1]), 2) if len(vols) > 1 else None
        oi_change_pct = round(oi_changes[-1] / max(1, abs(float(last.get("open_interest") or 0) - oi_changes[-1])) * 100, 2) if oi_changes else None
        evidence = classify_option_eod_evidence(premium_change_pct=premium_change,
            volume=last.get("volume"), volume_avg=volume_avg, oi_change_pct=oi_change_pct)
        options.append({"symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "premium_close": last.get("close"),
            "premium_change_pct": premium_change, "volume": last.get("volume"),
            "volume_avg": volume_avg, "open_interest": last.get("open_interest"),
            "oi_change": last.get("oi_change"), "oi_change_pct": oi_change_pct,
            "spot": spot or None, "moneyness": "ITM" if itm else "OTM_OR_ATM",
            "days_to_expiry": (date.fromisoformat(expiry) - date.fromisoformat(as_of)).days if expiry else None,
            "bid_ask_spread": "DATA_INSUFFICIENT", "liquidity": "EOD_VOLUME_ONLY",
            **evidence})
    # Persist option observations separately from the stock qualification snapshot.
    option_snapshot_count = 0
    options_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for option in options:
        options_by_symbol.setdefault(option["symbol"], []).append(option)
    if options_by_symbol:
        option_store = AirMonthlyPdStore()
        try:
            for symbol, symbol_options in options_by_symbol.items():
                stock = next((row for row in stocks if row["symbol"] == symbol), None)
                if not stock or not stock.get("levels") or not stock.get("reference_date"):
                    continue
                cycle = option_store.save_cycle(
                    instrument_type="EQUITY", symbol=symbol,
                    cycle_month=stock["cycle_month"], reference_date=stock["reference_date"],
                    pml=stock["levels"]["pml"], pmh=stock["levels"]["pmh"], eq=stock["levels"]["eq"])
                option_store.save_snapshot(
                    cycle_id=cycle["cycle_id"], as_of_date=as_of,
                    snapshot_type="OPTIONS_DAILY_EOD", support_status="STOCK_QUALIFIED",
                    pattern=(stock.get("pattern") or {}).get("pattern", "NONE"),
                    pattern_state=(stock.get("pattern") or {}).get("state", "INCOMPLETE"),
                    evidence={"options": symbol_options,
                              "disclosure": "EOD-only contract evidence; no bid/ask spread or intraday liquidity data."},
                    forecast={"option_contract_count": len(symbol_options)}, actual={})
                option_snapshot_count += 1
        finally:
            option_store.close()
    waiting_for_reference = bool(stocks) and all(
        item.get("reason") == "Monthly reference session has not completed as of the requested scan date"
        for item in stocks
    )
    scan_status = "WAITING_FOR_REFERENCE_SESSION" if waiting_for_reference else "COMPLETED"
    return {"status": scan_status, "as_of_date": as_of, "timeframe": "DAILY_EOD",
        "universe": {"index_counts": registry["index_counts"],
                     "unique_symbol_count": registry["unique_symbol_count"]},
        "coverage": {"symbols": len(stocks),
                     "ready": sum(x["coverage"]["status"] == "READY" for x in stocks),
                     "insufficient": sum(x["coverage"]["status"] != "READY" for x in stocks)},
        "stock_results": stocks, "qualified_stock_symbols": sorted(qualified_symbols),
        "persisted_stock_snapshots": persisted, "persisted_option_snapshots": option_snapshot_count,
        "options_results": options,
        "options_disclosure": "Options are scanned only after stock qualification. EOD bhavcopy does not contain historical bid/ask; options are WATCH only until all required evidence is available.",
        "broker_orders_placed": False}
