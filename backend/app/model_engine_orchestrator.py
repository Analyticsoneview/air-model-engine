"""Post-import AIR strategy replay coordinator.

This is the shared completion gate for initial NSE bootstrap, nightly refresh and
recovery after partial NSE downloads. It runs the existing deterministic replay
engines without invoking HTTP routes or sending Telegram notifications.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from app.model_engine_expiry78 import evaluate_expiry78_rows
from app.model_engine_ledger import ModelEngineLedger
from app.model_engine_master import build_master
from app.model_engine_original366 import evaluate_original366_rows


def run_post_import_strategy_cycle(as_of: str | None = None) -> dict[str, Any]:
    """Run every currently implemented EOD replay for configured AIR customers.

    RECOVERED is the ORIGINAL366 alternative-exit replay. RECOVERY is still a
    deferred MASTER view (not an executable replay engine); EXPIRYSCAN consumes
    separately captured Dhan option-chain snapshots and is not an NSE EOD replay.
    """
    cutoff = as_of or date.today().isoformat()
    customer_ids = sorted({
        value.strip()
        for value in os.getenv("AIR_OPERATOR_CUSTOMER_IDS", "").split(",")
        if value.strip()
    })
    if not customer_ids:
        return {
            "status": "NOT_CONFIGURED",
            "as_of": cutoff,
            "customers": 0,
            "note": "AIR_OPERATOR_CUSTOMER_IDS is empty; expired FO cleanup must remain deferred.",
        }

    ledger = ModelEngineLedger()
    customer_results: list[dict[str, Any]] = []
    try:
        for customer_id in customer_ids:
            rows = ledger.list_signals(customer_id, 2000)
            expiry78 = evaluate_expiry78_rows(rows, as_of=cutoff)
            original366 = evaluate_original366_rows(rows, as_of=cutoff)
            master = build_master(rows)
            expiry78_trades = [
                trade
                for contract in expiry78
                for trade in (contract.get("expiry78") or {}).get("trades", [])
            ]
            original366_trades = [
                trade
                for contract in original366
                for trade in (contract.get("original366") or {}).get("trades", [])
            ]
            customer_results.append({
                "customer": customer_id,
                "ledger_signals": len(rows),
                "master_signals": master.get("count", 0),
                "survivors": (master.get("counts") or {}).get("SURVIVOR", 0),
                "EXPIRY78": {
                    "contracts_replayed": len(expiry78),
                    "trades": len(expiry78_trades),
                    "expired": sum(
                        str(trade.get("classification") or "").upper() == "EXPIRED"
                        for trade in expiry78_trades
                    ),
                },
                "RECOVERED": {
                    "contracts_replayed": len(original366),
                    "trades": len(original366_trades),
                    "expired": sum(
                        str(trade.get("classification") or "").upper()
                        in ("EXPIRED", "EXPIRED_WIN", "EXPIRED_LOSS")
                        for trade in original366_trades
                    ),
                },
            })
    finally:
        ledger.close()

    return {
        "status": "COMPLETED",
        "as_of": cutoff,
        "customers": len(customer_results),
        "results": customer_results,
        "not_run": {
            "RECOVERY": "DEFERRED_NO_EXECUTOR",
            "EXPIRYSCAN": "SEPARATE_DHAN_SNAPSHOT_WORKFLOW_NOT_NSE_EOD_REPLAY",
        },
        "note": "Existing EOD replay engines completed without sending alerts or placing orders. Expired FO evidence snapshot and cleanup may now proceed.",
    }
