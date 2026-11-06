"""Evidence-first EXPIRYSCAN from persisted Dhan option-chain observations.

EXPIRYSCAN is a research watchlist, never an automatic entry/order. Missing
volume, OI or bid/ask evidence is explicitly flagged rather than inferred.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.air_qoc_store import AirQocStore


def scan_expiries(store: AirQocStore, *, account_id: str, today: date | None = None,
                  max_dte: int = 45, limit: int = 2000) -> dict[str, Any]:
    today = today or date.today()
    # Latest observation PER CONTRACT, not simply the most recent N raw rows.
    observations = store.db.execute("""
        SELECT * FROM (
          SELECT o.*, ROW_NUMBER() OVER (
            PARTITION BY underlying_scrip, underlying_segment, expiry, strike, option_type
            ORDER BY observed_at DESC, id DESC
          ) AS rn
          FROM option_observations o
          WHERE provider='dhan' AND account_id=?
        ) ranked WHERE rn=1 ORDER BY expiry, underlying_scrip, strike, option_type
    """, (account_id,)).fetchall()
    candidates: list[dict[str, Any]] = []
    for raw in observations:
        row = dict(raw)
        try:
            dte = (date.fromisoformat(row["expiry"]) - today).days
        except (TypeError, ValueError):
            continue
        if not 0 <= dte <= max_dte:
            continue
        bid, ask = row["bid_price"], row["ask_price"]
        volume, oi = row["volume"], row["open_interest"]
        checks = {
            "positive_volume": volume is not None and volume > 0,
            "positive_oi": oi is not None and oi > 0,
            "two_sided_quote": bid is not None and ask is not None and bid > 0 and ask >= bid,
        }
        spread_pct = (100 * (ask - bid) / ((ask + bid) / 2)) if checks["two_sided_quote"] else None
        # Configurable scan criteria are deliberately transparent; do not equate
        # these checks with AIR QOC signal qualification.
        checks["spread_at_most_10pct"] = spread_pct is not None and spread_pct <= 10
        missing = [key for key in ("volume", "open_interest", "bid_price", "ask_price")
                   if row[key] is None]
        status = ("LIQUIDITY_SCREEN_PASSED" if all(checks.values())
                  else "INSUFFICIENT_DATA" if missing else "WATCH_NOT_QUALIFIED")
        candidates.append({
            "underlying_scrip": row["underlying_scrip"],
            "underlying_segment": row["underlying_segment"],
            "symbol": str(row["underlying_scrip"]),
            "security_id": row["security_id"],
            "option_type": row["option_type"],
            "expiry": row["expiry"],
            "strike": row["strike"],
            "days_to_expiry": dte,
            "survivor": dte <= 7,
            "last_price": row["last_price"],
            "underlying_price": row["underlying_price"],
            "volume": volume,
            "previous_volume": row["previous_volume"],
            "open_interest": oi,
            "previous_oi": row["previous_oi"],
            "oi_change": oi - row["previous_oi"] if oi is not None and row["previous_oi"] is not None else None,
            "bid_price": bid,
            "ask_price": ask,
            "spread_pct": round(spread_pct, 2) if spread_pct is not None else None,
            "observed_at": row["observed_at"],
            "checks": checks,
            "missing_evidence": missing,
            "scan_status": status,
            "classification": "EXPIRYSCAN",
            "qoc_score": None,
            "entry": None,
            "stop_loss": None,
            "targets": None,
        })
    candidates.sort(key=lambda r: (
        0 if r["survivor"] else 1,
        r["days_to_expiry"],
        0 if r["scan_status"] == "LIQUIDITY_SCREEN_PASSED" else 1,
        -(r["volume"] or 0),
    ))
    return {
        "classification": "EXPIRYSCAN",
        "as_of": today.isoformat(),
        "max_dte": max_dte,
        "total_contracts": len(candidates),
        "returned": min(limit, len(candidates)),
        "survivor_count": sum(r["survivor"] for r in candidates),
        "qualified_trade_signals": 0,
        "note": "Evidence-based expiry/liquidity screen only. No QOC score, entry, SL, targets or order without full underlying and options confirmation.",
        "rows": candidates[:limit],
    }
