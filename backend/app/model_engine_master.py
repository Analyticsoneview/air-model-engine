"""Canonical AIR MASTER lifecycle aggregation.

This module only aggregates persisted, verified ledger rows. It never invents signals,
orders, entry prices, or P&L. SURVIVOR applies the EXPIRY78 pre-expiry-entry cohort to
active contracts that have not expired; expiry-day entries are excluded.
"""
from __future__ import annotations

from typing import Any

# Stable public vocabulary shared by API and clients. Icons are intentionally omitted
# until the user's exact pinned icon legend is confirmed.
MASTER_COMMANDS = (
    "MASTER", "OPEN", "NEW", "HOLD", "REENTRY", "SLHIT", "SURVIVOR",
    "WAIT", "EXPIRY78", "ORIGINAL366", "RECOVERY", "SUMMARY", "AUDIT", "COMBINED",
)
LIFECYCLE_STATUSES = ("NEW", "HOLD", "RE-ENTRY", "SL", "TARGETS", "EXPIRED", "EXPIRYSCAN")
MASTER_GROUPS = ("OPEN", "NEW", "HOLD", "REENTRY", "SURVIVOR", "WAIT",
                 "SLHIT", "TARGETS", "EXPIRED", "EXPIRYSCAN", "COMBINED")


def _dte(row: dict[str, Any]) -> int | None:
    value = row.get("days_to_expiry")
    return int(value) if isinstance(value, (int, float)) else None


def _is_pre_expiry_survivor_candidate(row: dict[str, Any]) -> bool:
    """Apply the broker-restricted EXPIRY78 cohort rule to live positions.

    A candidate must still be unexpired, have a verified entry date strictly before
    expiry, and remain in an active lifecycle classification. The historical
    0–7-DTE marker is not the survivor definition.
    """
    status = str(row.get("classification") or "").upper()
    if status not in ("NEW", "HOLD", "RE-ENTRY", "REENTRY"):
        return False
    dte = _dte(row)
    if dte is None or dte < 0:
        return False
    entry_date = str(row.get("entry_date") or "").strip()
    expiry = str(row.get("expiry") or "").strip()
    if not entry_date or not expiry:
        return False
    try:
        return entry_date[:10] < expiry[:10]
    except (TypeError, ValueError):
        return False


def _sort_key(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("signal_date") or ""),
        -float(row.get("entry_price") or 0),
        str(row.get("symbol") or ""),
        str(row.get("expiry") or ""),
        float(row.get("strike") or 0),
    )


def build_master(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build canonical MASTER groups with deterministic contract deduplication."""
    # One ledger row per signal_id is guaranteed by the store primary key. Defensively
    # collapse repeated ids in case an alternate data source is added later.
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("signal_id") or "|".join(str(row.get(k) or "") for k in
                   ("symbol", "option_type", "expiry", "strike", "entry_date")))
        unique.setdefault(key, row)
    all_rows = list(unique.values())

    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in MASTER_GROUPS}
    for row in all_rows:
        status = str(row.get("classification") or "").upper()
        dte = _dte(row)
        if status == "EXPIRED" or (dte is not None and dte < 0):
            groups["EXPIRED"].append(row)
        elif status == "NEW":
            groups["NEW"].append(row)
        elif status == "HOLD":
            groups["HOLD"].append(row)
        elif status in ("RE-ENTRY", "REENTRY"):
            groups["REENTRY"].append(row)
        elif status in ("SL", "SLHIT"):
            groups["SLHIT"].append(row)
        elif status == "TARGETS":
            groups["TARGETS"].append(row)
        elif status == "EXPIRYSCAN":
            groups["EXPIRYSCAN"].append(row)

        if _is_pre_expiry_survivor_candidate(row):
            candidate = dict(row)
            candidate["survivor_eligible"] = True
            candidate["survivor_rule"] = "EXPIRY78_PRE_EXPIRY_ENTRY"
            candidate["survivor_reason"] = (
                "Active contract; entry recorded before expiry; contract has not expired."
            )
            groups["SURVIVOR"].append(candidate)

    # OPEN is the union of currently open lifecycle entries, not a second copy of rows.
    groups["OPEN"] = groups["NEW"] + groups["HOLD"]
    groups["COMBINED"] = all_rows
    # Evidence-backed breakdowns; unknown sectors remain explicitly unclassified.
    instrument_counts = {"INDEX": 0, "STOCK": 0, "OTHER_OR_UNKNOWN": 0}
    sector_counts: dict[str, int] = {}
    for row in all_rows:
        kind = str(row.get("instrument_type") or "").upper()
        if kind in ("INDEX", "INDICES"):
            instrument_counts["INDEX"] += 1
        elif kind in ("STOCK", "EQUITY"):
            instrument_counts["STOCK"] += 1
        else:
            instrument_counts["OTHER_OR_UNKNOWN"] += 1
        sector = str(row.get("sector") or "UNCLASSIFIED").strip().upper()
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    # WAIT is intentionally empty until a verified pending-state source is implemented.
    for name in groups:
        groups[name].sort(key=_sort_key, reverse=True)

    return {
        "vocabulary": {
            "commands": list(MASTER_COMMANDS),
            "lifecycle_statuses": list(LIFECYCLE_STATUSES),
            "implemented_views": ["MASTER", *MASTER_GROUPS, "SUMMARY", "AUDIT"],
            "deferred_views": ["EXPIRY78", "ORIGINAL366", "RECOVERY"],\n            "survivor_rule": "EXPIRY78_PRE_EXPIRY_ENTRY",\n            "survivor_exclusions": ["EXPIRED_CONTRACT", "ENTRY_ON_OR_AFTER_EXPIRY", "INACTIVE_LIFECYCLE", "MISSING_ENTRY_OR_EXPIRY"],
        },
        "count": len(all_rows),
        "counts": {name: len(items) for name, items in groups.items()},
        "groups": groups,
        "breakdowns": {
            "instrument_type": instrument_counts,
            "sector": dict(sorted(sector_counts.items(), key=lambda item: (-item[1], item[0]))),
            "option_type": {
                "CE": sum(1 for r in all_rows if str(r.get("option_type") or "").upper() == "CE"),
                "PE": sum(1 for r in all_rows if str(r.get("option_type") or "").upper() == "PE"),
            },
        },
        "summary": {
            "unique_signals": len(all_rows),
            "open": len(groups["OPEN"]),
            "new": len(groups["NEW"]),
            "hold": len(groups["HOLD"]),
            "reentry": len(groups["REENTRY"]),
            "slhit": len(groups["SLHIT"]),
            "survivor_watch": len(groups["SURVIVOR"]),\n            "survivor_rule": "EXPIRY78_PRE_EXPIRY_ENTRY",
            "wait": len(groups["WAIT"]),
            "expired": len(groups["EXPIRED"]),
            "targets": len(groups["TARGETS"]),
            "expiry_scan": len(groups["EXPIRYSCAN"]),
            "pnl": sum(float(r.get("pnl") or 0) for r in all_rows),
        },
        "audit": {
            "deduplicated": len(rows) - len(all_rows),
            "missing_expiry": sum(1 for r in all_rows if not r.get("expiry")),
            "missing_entry_price": sum(1 for r in all_rows if r.get("entry_price") is None),
            "missing_sector": sum(1 for r in all_rows if not r.get("sector")),
            "wait_source": "NOT_IMPLEMENTED",
            "note": "Only persisted verified ledger records are aggregated; no signals are inferred.",
        },
    }
