"""Independent strategy views for AIR Model Engine.

The views share a verified ledger but never share qualification membership.
Historical ORIGINAL366 baseline metrics are constants and are not recomputed
from the filtered live candidate set.
"""
from __future__ import annotations

from typing import Any

STOCK_ENTRY_MIN = 1.0
STOCK_ENTRY_MAX = 10.0

ORIGINAL366_BASELINE = {
    "trades": 366,
    "expiry_winners": 32,
    "five_percent_stop_losses": 334,
    "gross_pnl_rupees": 1071850,
    "charges_rupees": 21602,
    "net_pnl_rupees": 1050248,
    "capital_rupees": 1514362,
    "baseline_status": "PRESERVED_NOT_RECALCULATED",
}

STRATEGY_RULES = {
    "EXPIRY78": {
        "name": "EXPIRY78",
        "membership": "EXPIRY78",
        "stock_entry_filter": "₹1–₹10 entry premium for stock CE/PE; index options retain existing rules",
        "qualification": "Existing EXPIRY78 pre-expiry-entry rule: active NEW/HOLD/verified RE-ENTRY, valid entry and expiry, entry strictly before expiry, DTE >= 0. Expiry-day entries and expired/inactive/missing-date records are excluded.",
        "candidate_filter_stage": "ENTRY_QUALIFICATION",
    },
    "ORIGINAL366": {
        "name": "ORIGINAL 366",
        "membership": "ORIGINAL366",
        "stock_entry_filter": "₹1–₹10 applies only when qualifying new stock CE/PE candidates; index options retain existing rules",
        "qualification": "Keep original 366-trade historical baseline immutable. Filter only newly qualifying stock-option candidates; do not rewrite historical baseline until an explicit recalculation.",
        "candidate_filter_stage": "NEW_CANDIDATE_QUALIFICATION",
    },
    "RECOVERY": {
        "name": "RECOVERY",
        "membership": "RECOVERY",
        "stock_entry_filter": "₹1–₹10 applies to qualifying stock CE/PE recovery entries; index options retain existing rules",
        "qualification": "After the initial 5% SL, a daily option close above the original entry premium qualifies a recovery signal; enter at the next session open and set a fresh 5% SL from the recovery entry. The recovery entry has a 10-trading-session shelf life measured from the recovery re-entry date. A later daily HIGH reaching recovery-entry × 1.50 marks +50% target-qualified and the position is then held to expiry. Trail milestones +50/+100/+200/+300% at +45/+90/+180/+270%; if target and stop occur in the same candle, assume stop first. Lot size >1,250 requires original entry premium < ₹1.",
        "candidate_filter_stage": "RECOVERY_ENTRY_QUALIFICATION",
    },
}

_STATUS_ALIASES = {
    "NEW": "NEW",
    "HOLD": "HOLD",
    "WAIT": "WAIT",
    "RE-ENTRY": "REENTRY",
    "REENTRY": "REENTRY",
    "SL": "SLHIT",
    "SLHIT": "SLHIT",
    "SL HIT": "SLHIT",
    "EXPIRED": "EXPIRED",
    "TARGETS": "TARGETS",
}


def _status(row: dict[str, Any]) -> str:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    raw = str(evidence.get("lifecycle_status") or row.get("classification") or "").upper()
    return _STATUS_ALIASES.get(raw, raw)


def _memberships(row: dict[str, Any]) -> set[str]:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    values = evidence.get("strategy_memberships") or evidence.get("strategies") or []
    if isinstance(values, str):
        values = [values]
    result = {str(value).upper().replace(" ", "") for value in values}
    single = evidence.get("strategy") or row.get("strategy")
    if single:
        result.add(str(single).upper().replace(" ", ""))
    return result


def _is_stock_option(row: dict[str, Any]) -> bool:
    instrument = str(row.get("instrument_type") or "").upper()
    option_type = str(row.get("option_type") or "").upper()
    return instrument in ("STOCK", "EQUITY") and option_type in ("CE", "PE")


def _stock_entry_filter_passes(row: dict[str, Any]) -> bool:
    if not _is_stock_option(row):
        return True
    premium = row.get("entry_price")
    try:
        premium = float(premium)
    except (TypeError, ValueError):
        return False
    return STOCK_ENTRY_MIN <= premium <= STOCK_ENTRY_MAX


def _active_expiry78(row: dict[str, Any]) -> bool:
    status = _status(row)
    if status not in ("NEW", "HOLD", "REENTRY"):
        return False
    expiry = str(row.get("expiry") or "")[:10]
    entry = str(row.get("entry_date") or "")[:10]
    dte = row.get("days_to_expiry")
    return bool(expiry and entry and entry < expiry and
                isinstance(dte, (int, float)) and dte >= 0)


def _candidate_filter_applies(status: str, strategy: str) -> bool:
    if strategy == "EXPIRY78":
        return status in ("NEW", "REENTRY")
    if strategy == "ORIGINAL366":
        return status == "NEW"
    if strategy == "RECOVERY":
        return status == "REENTRY"
    return False


def _recovery_verified(row: dict[str, Any]) -> bool:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    # Recovery is opt-in only from an evidence-backed recovery pipeline. Never
    # infer a recovery from a plain RE-ENTRY classification.
    if evidence.get("recovery_verified") is not True:
        return False
    lot_size = row.get("lot_size")
    if not isinstance(lot_size, (int, float)) or lot_size <= 0:
        return False
    if lot_size > 1250:
        original_premium = evidence.get("original_entry_premium")
        if original_premium is None:
            original_premium = evidence.get("original_entry_price")
        try:
            return float(original_premium) < 1.0
        except (TypeError, ValueError):
            return False
    return True


def _sort_key(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("signal_date") or ""),
        float(row.get("entry_price") or 0),
        str(row.get("symbol") or ""),
        str(row.get("expiry") or ""),
        float(row.get("strike") or 0),
    )


def build_strategy_views(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build three isolated strategy tabs with independent lifecycle groups."""
    result: dict[str, Any] = {}
    for strategy, rules in STRATEGY_RULES.items():
        groups = {key: [] for key in
                  ("OPEN", "NEW", "HOLD", "WAIT", "SLHIT", "REENTRY", "EXPIRED", "TARGETS")}
        accepted: list[dict[str, Any]] = []
        rejected_stock_filter = 0
        rejected_recovery_proof = 0
        for row in rows:
            status = _status(row)
            memberships = _memberships(row)
            # EXPIRY78 keeps its canonical pre-expiry active cohort. Other
            # lifecycle states enter only with explicit model membership.
            member = (strategy in memberships or
                      (strategy == "EXPIRY78" and _active_expiry78(row)))
            if not member:
                continue
            if _candidate_filter_applies(status, strategy) and not _stock_entry_filter_passes(row):
                rejected_stock_filter += 1
                continue
            if strategy == "RECOVERY" and status == "REENTRY" and not _recovery_verified(row):
                rejected_recovery_proof += 1
                continue
            accepted.append(row)
            bucket = status if status in groups else None
            if bucket:
                groups[bucket].append(row)
        groups["OPEN"] = groups["NEW"] + groups["HOLD"]
        for values in groups.values():
            values.sort(key=_sort_key, reverse=True)
        result[strategy] = {
            "rules": rules,
            "count": len(accepted),
            "counts": {key: len(value) for key, value in groups.items()},
            "groups": groups,
            "audit": {
                "stock_candidates_rejected_outside_1_to_10": rejected_stock_filter,
                "recovery_candidates_rejected_without_verified_recovery_evidence": rejected_recovery_proof,
                "membership_source": "explicit evidence.strategy_memberships/strategies; EXPIRY78 also uses canonical pre-expiry eligibility",
            },
        }
        if strategy == "ORIGINAL366":
            result[strategy]["baseline"] = dict(ORIGINAL366_BASELINE)
    return result
