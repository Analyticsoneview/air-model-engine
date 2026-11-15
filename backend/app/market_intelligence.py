"""Evidence-backed market intelligence derived from official NSE EOD records."""
from __future__ import annotations

from app.nse_bhavcopy import nse_data_rows, nse_data_status


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_market_intelligence_pulse() -> dict:
    status = nse_data_status()
    cm = (status.get("markets") or {}).get("CM") or {}
    as_of = cm.get("last_date")
    breadth = {
        "status": "unavailable", "as_of": as_of, "advances": None,
        "declines": None, "unchanged": None, "total": 0,
        "advance_decline_ratio": None,
    }
    if as_of:
        rows = nse_data_rows("CM", end_date=as_of, instrument_type="STK", limit=5000)
        advances = declines = unchanged = 0
        for row in rows:
            close = _number(row.get("close"))
            previous = _number(row.get("previous_close"))
            if close is None or previous is None:
                continue
            if close > previous:
                advances += 1
            elif close < previous:
                declines += 1
            else:
                unchanged += 1
        total = advances + declines + unchanged
        if total:
            breadth = {
                "status": "available", "as_of": as_of,
                "advances": advances, "declines": declines,
                "unchanged": unchanged, "total": total,
                "advance_decline_ratio": round(advances / declines, 3) if declines else None,
            }
    return {
        "source": "NSE official UDiFF CM bhavcopy",
        "data_type": "EOD",
        "freshness": "latest_imported_session" if as_of else "no_imported_session",
        "as_of": as_of,
        "updated_at": status.get("updated_at"),
        "breadth": breadth,
        "indices": {
            "status": "unavailable",
            "reason": "No verified index quote feed is currently available to this customer session.",
        },
        "sectors": {
            "status": "unavailable",
            "reason": "NSE CM bhavcopy does not contain sector classifications; a verified sector master is required.",
        },
        "disclosure": "EOD breadth is based on the latest imported NSE cash-market session; it is not live market data.",
    }
