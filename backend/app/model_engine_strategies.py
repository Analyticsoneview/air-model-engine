"""Independent strategy views for AIR Model Engine.

The views share a verified ledger but never share qualification membership.
Historical ORIGINAL366 baseline metrics are constants and are not recomputed
from the filtered live candidate set.
"""
from __future__ import annotations

from typing import Any

from app.model_engine_expiry78 import evaluate_expiry78_rows
from app.model_engine_original366 import evaluate_original366_rows

STOCK_ENTRY_MIN = 1.0
STOCK_ENTRY_MAX = 10.0

ORIGINAL366_BASELINE = {
    "reference_cohort": "ORIGINAL366",
    "display_section": "RECOVERED",
    "source_entries": 534,
    "full_expiry_coverage_cohort": 366,
    "partial_coverage_excluded": 83,
    "no_post_entry_data_excluded": 85,
    "five_percent_sl_hits_in_full_coverage_cohort": 366,
    "same_day_sl_hits": 274,
    "later_session_sl_hits": 69,
    "gap_open_sl_hits": 23,
    "baseline_status": "COHORT_FILTER_ONLY",
}

STRATEGY_RULES = {
    "EXPIRY78": {
        "name": "EXPIRY78",
        "membership": "EXPIRY78",
        "stock_entry_filter": "₹1–₹10 entry premium for stock CE/PE; index options retain existing rules",
        "qualification": "Seven-rule replay: valid positive option OHLCV; bullish real-body engulfing against the previous valid traded observation; entry limit = 40% of engulfing HIGH; later daily LOW touch strictly before expiry; entry premium >= ₹1 and entry-day quantity >= 10; 5% protected stop with conservative same-day and gap-through handling; only unstopped positions with verified expiry intrinsic valuation qualify as survivors.",
        "candidate_filter_stage": "ENTRY_QUALIFICATION",
    },
    "ORIGINAL366": {
        "name": "RECOVERED",
        "membership": "ORIGINAL366",
        "stock_entry_filter": "Reference cohort was filtered using actual entry premium ₹1–₹10 for stock CE/PE; index options exempt; shelf_sessions at least 10",
        "qualification": "Display the 366 full-expiry-coverage records selected from the original 534-entry population. Preserve original 5% SLHIT. After SL, add a watch-only RECOVERED row when a verified daily option CLOSE is above original entry premium. This is not RECOVERY re-entry or an open position.",
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
    return instrument in ("STOCK", "EQUITY", "OPTSTK", "STOCK_OPTION") and option_type in ("CE", "PE")


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
                  ("OPEN", "NEW", "HOLD", "WAIT", "SLHIT", "REENTRY", "EXPIRED", "TARGETS", "RECOVERED")}
        accepted: list[dict[str, Any]] = []
        rejected_stock_filter = 0
        rejected_recovery_proof = 0
        for row in rows:
            status = _status(row)
            memberships = _memberships(row)
            # EXPIRY78 keeps its canonical pre-expiry active cohort. Other
            # lifecycle states enter only with explicit model membership.
            member = strategy in memberships or (
                strategy == "EXPIRY78" and
                isinstance(row.get("evidence"), dict) and
                row["evidence"].get("expiry78_candidate") is True
            )
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
                "membership_source": "explicit evidence.strategy_memberships/strategies or evidence.expiry78_candidate; no cross-strategy inference",
            },
        }
        if strategy == "ORIGINAL366":
            result[strategy]["baseline"] = dict(ORIGINAL366_BASELINE)

    # ORIGINAL366 replay replaces persisted lifecycle rows for the same signal IDs.
    # Invalid qualification evidence is excluded from active groups and surfaced
    # separately; expiry outcomes are grouped only under EXPIRED.
    original_evaluated = evaluate_original366_rows(rows)
    if original_evaluated:
        prior = result["ORIGINAL366"]["groups"]
        replayed_ids = {str(item.get("signal_id") or "") for item in original_evaluated}
        original_groups = {
            key: [row for row in prior.get(key, [])
                  if str(row.get("signal_id") or "") not in replayed_ids]
            for key in ("NEW", "HOLD", "WAIT", "SLHIT", "REENTRY", "EXPIRED", "TARGETS")
        }
        original_groups["OPEN"] = []
        original_groups["REJECTED"] = []
        original_groups["EXPIRED_WIN"] = []
        original_groups["EXPIRED_LOSS"] = []
        replay_trades = []
        for source in original_evaluated:
            replay = source.get("original366") or {}
            trades = replay.get("trades") or []
            if not trades:
                status = replay.get("status")
                if status == "REJECTED":
                    original_groups["REJECTED"].append({**source, "classification": "REJECTED", "reason": replay.get("reason")})
                else:
                    original_groups["WAIT"].append({**source, "classification": "WAIT", "reason": replay.get("reason")})
                continue
            for trade in trades:
                item = {**source, **trade, "strategy": "ORIGINAL366"}
                replay_trades.append(item)
                status = trade.get("classification")
                if status in ("EXPIRED_WIN", "EXPIRED_LOSS"):
                    original_groups["EXPIRED"].append(item)
                    original_groups[status].append(item)
                elif status in original_groups:
                    original_groups[status].append(item)
                if trade.get("recovered_watch"):
                    original_groups["RECOVERED"].append({
                        **item,
                        "classification": "RECOVERED_WATCH",
                        "watch": trade["recovered_watch"],
                        "position_status": "WATCH_ONLY_NOT_OPEN",
                    })
        original_groups["OPEN"] = original_groups["NEW"] + original_groups["HOLD"]
        for values in original_groups.values():
            values.sort(key=_sort_key, reverse=True)
        result["ORIGINAL366"]["groups"] = original_groups
        result["ORIGINAL366"]["counts"] = {key: len(value) for key, value in original_groups.items()}
        result["ORIGINAL366"]["count"] = sum(
            len(original_groups[key]) for key in
            ("NEW", "HOLD", "WAIT", "SLHIT", "REENTRY", "EXPIRED", "TARGETS", "REJECTED")
        )
        result["ORIGINAL366"]["replay"] = {
            "contracts_replayed": len(original_evaluated),
            "trades_replayed": len(replay_trades),
            "expiry_winners": len(original_groups["EXPIRED_WIN"]),
            "expiry_losses": len(original_groups["EXPIRED_LOSS"]),
            "stop_losses": len(original_groups["SLHIT"]),
            "gross_pnl_rupees": round(sum(item.get("gross_pnl_rupees") or 0 for item in replay_trades), 2),
            "charges_rupees": round(sum(item.get("charges_rupees") or 0 for item in replay_trades), 2),
            "net_pnl_rupees": round(sum(item.get("net_pnl_rupees") or 0 for item in replay_trades), 2),
            "baseline": dict(ORIGINAL366_BASELINE),
            "baseline_status": "COHORT_FILTER_ONLY",
        }

    # EXPIRY78's seven-rule engine is replayed only when verified daily option
    # OHLCV bars are attached to an explicitly tagged EXPIRY78 contract. Ledger
    # rows without source bars remain visible as persisted observations, but are
    # never represented as engine-qualified trades.
    evaluated = evaluate_expiry78_rows(rows)
    if evaluated:
        replayed_ids = {str(source.get("signal_id") or "") for source in evaluated}
        # Keep independently verified ledger lifecycle rows that do not carry
        # replay bars (notably separately verified REENTRY records).
        engine_groups = {key: [
            item for item in groups[key]
            if str(item.get("signal_id") or "") not in replayed_ids
        ] for key in ("NEW", "HOLD", "WAIT", "SLHIT", "REENTRY", "EXPIRED", "TARGETS")}
        engine_groups["OPEN"] = []
        engine_trade_count = 0
        engine_survivors = 0
        engine_stops = 0
        contracts_without_entry_touch = 0
        for source in evaluated:
            replay = source["expiry78"]
            trades = replay.get("trades") or []
            if not trades:
                contracts_without_entry_touch += 1
                engine_groups["WAIT"].append({
                    **source, "classification": "WAIT",
                    "reason": replay.get("reason"),
                    "position_status": "WAIT",
                })
            for trade in trades:
                item = {**source, **trade, "strategy": "EXPIRY78"}
                bucket = {"SL": "SLHIT", "RE-ENTRY": "REENTRY"}.get(
                    str(trade.get("classification") or "").upper(),
                    str(trade.get("classification") or "").upper(),
                )
                if bucket in engine_groups:
                    engine_groups[bucket].append(item)
                engine_trade_count += 1
                engine_survivors += int(bool(trade.get("expiry_survivor")))
                engine_stops += int(trade.get("classification") == "SL")
        engine_groups["OPEN"] = engine_groups["NEW"] + engine_groups["HOLD"]
        for values in engine_groups.values():
            values.sort(key=_sort_key, reverse=True)
        result["EXPIRY78"]["groups"] = engine_groups
        result["EXPIRY78"]["counts"] = {key: len(value) for key, value in engine_groups.items()}
        result["EXPIRY78"]["count"] = sum(
            len(engine_groups[key]) for key in
            ("NEW", "HOLD", "WAIT", "SLHIT", "REENTRY", "EXPIRED", "TARGETS")
        )
        result["EXPIRY78"]["audit"].update({
            "engine": "AIR_EXPIRY78_SEVEN_RULES",
            "contracts_replayed": len(evaluated),
            "trades_replayed": engine_trade_count,
            "expiry_survivors": engine_survivors,
            "stop_losses": engine_stops,
            "contracts_without_entry_touch": contracts_without_entry_touch,
            "note": "Only verified daily OHLCV evidence is replayed; contracts without attached daily bars are not backfilled or guessed.",
        })
    return result
