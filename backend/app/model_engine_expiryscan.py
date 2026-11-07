"""Evidence-first EXPIRYSCAN from persisted provider-normalized option-chain observations.

EXPIRYSCAN is a research watchlist, never an automatic entry/order. Missing
volume, OI or bid/ask evidence is explicitly flagged rather than inferred.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.air_qoc_store import AirQocStore


def scan_expiries(store: AirQocStore, *, account_id: str, provider: str = "dhan",
                  today: date | None = None, max_dte: int = 45,
                  limit: int = 2000) -> dict[str, Any]:
    today = today or date.today()
    # Latest observation PER CONTRACT, not simply the most recent N raw rows.
    observations = store.db.execute("""
        SELECT * FROM (
          SELECT o.*, ROW_NUMBER() OVER (
            PARTITION BY underlying_scrip, underlying_segment, expiry, strike, option_type
            ORDER BY observed_at DESC, id DESC
          ) AS rn
          FROM option_observations o
          WHERE provider=? AND account_id=?
        ) ranked WHERE rn=1 ORDER BY expiry, underlying_scrip, strike, option_type
    """, (provider, account_id)).fetchall()
    candidates: list[dict[str, Any]] = []

    def previous_weekday(day: date) -> date:
        candidate = date.fromordinal(day.toordinal() - 1)
        while candidate.weekday() >= 5:
            candidate = date.fromordinal(candidate.toordinal() - 1)
        return candidate

    for raw in observations:
        row = dict(raw)
        try:
            expiry_date = date.fromisoformat(str(row["expiry"]))
        except (TypeError, ValueError):
            # Invalid or missing expiry cannot be safely labelled EXPIRED.
            continue
        dte = (expiry_date - today).days
        is_expired = dte < 0
        if not is_expired and dte > max_dte:
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
        status = ("EXPIRED" if is_expired else
                  "LIQUIDITY_SCREEN_PASSED" if all(checks.values()) else
                  "INSUFFICIENT_DATA" if missing else "WATCH_NOT_QUALIFIED")
        close_before_date = previous_weekday(expiry_date) if not is_expired else None
        close_alert_due = bool(close_before_date and today == close_before_date)
        candidates.append({
            "provider": provider,
            "underlying_scrip": row["underlying_scrip"],
            "underlying_segment": row["underlying_segment"],
            "symbol": str(row["underlying_scrip"]),
            "security_id": row["security_id"],
            "option_type": row["option_type"],
            "expiry": row["expiry"],
            "strike": row["strike"],
            "days_to_expiry": dte,
            "expiry_date_valid": True,
            "expired": is_expired,
            "close_before_expiry_date": close_before_date.isoformat() if close_before_date else None,
            "close_alert_due": close_alert_due,
            "notification": ({
                "type": "EXPIRY_CLOSE_REMINDER",
                "message": "Review and close this EXPIRYSCAN contract before expiry.",
                "due_date": today.isoformat(),
                "expiry": row["expiry"],
            } if close_alert_due else None),
            "survivor": (not is_expired and dte <= 7),
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
            "classification": "EXPIRED" if is_expired else "EXPIRYSCAN",
            "position_status": "EXPIRED" if is_expired else "OBSERVATION",
            "expiry_status_reason": (
                "Valid expiry date is before the scan date."
                if is_expired else "Valid future expiry date."
            ),
            "qoc_score": None,
            "entry": None,
            "stop_loss": None,
            "targets": None,
        })
    future_candidates = [r for r in candidates if not r["expired"]]
    expired_candidates = [r for r in candidates if r["expired"]]
    close_alerts = [r for r in future_candidates if r["close_alert_due"]]
    sort_key = lambda r: (
        0 if r["survivor"] else 1,
        r["days_to_expiry"],
        0 if r["scan_status"] == "LIQUIDITY_SCREEN_PASSED" else 1,
        -(r["volume"] or 0),
    )
    future_candidates.sort(key=sort_key)
    expired_candidates.sort(key=lambda r: (r["expiry"], r["symbol"], r["strike"], r["option_type"]))
    return {
        "classification": "EXPIRYSCAN",
        "as_of": today.isoformat(),
        "max_dte": max_dte,
        "total_contracts": len(future_candidates),
        "returned": min(limit, len(future_candidates)),
        "survivor_count": sum(r["survivor"] for r in future_candidates),
        "expired_count": len(expired_candidates),
        "expired_rows_returned": min(limit, len(expired_candidates)),
        "close_alert_count": len(close_alerts),
        "close_alerts": close_alerts[:limit],
        "qualified_trade_signals": 0,
        "note": "Valid future expiry dates within max_dte remain in EXPIRYSCAN. Valid past expiry dates are separately classified EXPIRED. close_alerts flags the prior weekday as the reminder date; exchange holidays require the exchange calendar and are not inferred. This is an evidence-only screen, not an order or auto-close.",
        "rows": future_candidates[:limit],
        "expired_rows": expired_candidates[:limit],
    }
