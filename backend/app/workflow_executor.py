"""Allowlisted AIR workflow step executor.

Only named, read-only research and notification adapters are callable. No dynamic
imports, arbitrary code, shell commands or broker order actions are supported.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.workflow_engine import WorkflowStore
from app.workflow_events import build_idempotency_key

log = logging.getLogger("air.workflow.executor")


class WorkflowStepError(RuntimeError):
    pass


def _customer_id(context: dict) -> str:
    customer_id = str(context.get("event_payload", {}).get("customer_id") or "").strip()
    if not customer_id:
        raise WorkflowStepError("A customer-scoped workflow action requires customer_id in its event")
    return customer_id


def _step_input(params: dict, outputs: dict[str, dict]) -> dict:
    source_step = params.get("source_step")
    if not source_step:
        return {}
    if source_step not in outputs:
        raise WorkflowStepError(f"Workflow source step {source_step} has no completed output")
    return outputs[source_step]


def _execute_action(
    store: WorkflowStore, context: dict, step: dict, outputs: dict[str, dict],
) -> dict[str, Any]:
    action = str(step["action"]).lower()
    params = step.get("params") or {}
    event_payload = context.get("event_payload") or {}
    source_output = _step_input(params, outputs)

    if action == "qoc.qualify":
        from app.air_qoc_store import AirQocStore
        from app.air_qoc_qualification import qualify_option_observations

        account_id = str(params.get("account_id") or event_payload.get("account_id") or "")
        if not account_id:
            raise WorkflowStepError("qoc.qualify requires account_id in params or event")
        qoc_store = AirQocStore()
        try:
            observations = qoc_store.qualification_history(
                account_id=account_id,
                provider=str(params.get("provider") or event_payload.get("provider") or "dhan"),
                underlying_scrip=params.get("underlying_scrip"),
                expiry=params.get("expiry"),
                limit=max(2, min(int(params.get("limit", 10000)), 20000)),
            )
        finally:
            qoc_store.close()
        result = qualify_option_observations(
            observations, mode=str(params.get("mode", "LIVE")).upper(),
            max_candidates=max(1, min(int(params.get("max_candidates", 50)), 100)),
        )
        return {
            "mode": result.get("mode"), "as_of": result.get("as_of"),
            "counts": result.get("counts", {}),
            "contracts_evaluated": result.get("contracts_evaluated", 0),
            "signals": result.get("signals", []),
            "disclosure": result.get("disclosure"),
        }

    if action == "qoc.backtest":
        from app.air_qoc_store import AirQocStore
        from app.air_qoc_qualification import backtest_option_observations

        account_id = str(params.get("account_id") or event_payload.get("account_id") or "")
        if not account_id:
            raise WorkflowStepError("qoc.backtest requires account_id in params or event")
        qoc_store = AirQocStore()
        try:
            observations = qoc_store.qualification_history(
                account_id=account_id,
                provider=str(params.get("provider") or event_payload.get("provider") or "dhan"),
                underlying_scrip=params.get("underlying_scrip"),
                expiry=params.get("expiry"),
                limit=max(2, min(int(params.get("limit", 10000)), 20000)),
            )
        finally:
            qoc_store.close()
        result = backtest_option_observations(
            observations, from_date=params.get("from_date"), to_date=params.get("to_date"),
            stop_loss_pct=float(params.get("stop_loss_pct", 30.0)),
            session_cutoff=str(params.get("session_cutoff", "15:20")),
        )
        return {
            "trades": result.get("trades", [])[:100],
            "trade_count": result.get("trade_count", len(result.get("trades", []))),
            "summary": result.get("summary", {}),
            "disclosure": result.get("disclosure"),
        }

    if action == "portfolio.overview":
        from app.portfolio_risk import PortfolioRiskStore

        risk_store = PortfolioRiskStore()
        try:
            result = risk_store.overview(_customer_id(context))
        finally:
            risk_store.close()
        return {
            "summary": result.get("summary", {}),
            "accounts": [
                {"broker": row.get("broker"), "account_id": row.get("account_id"),
                 "summary": row.get("summary", {})}
                for row in result.get("accounts", [])
            ],
            "data_quality": result.get("data_quality"),
        }

    if action == "event.emit":
        event_type = str(params.get("event_type") or "").strip()
        payload = params.get("payload") or {}
        if not isinstance(payload, dict):
            raise WorkflowStepError("event.emit params.payload must be an object")
        payload = {
            **payload,
            "customer_id": payload.get("customer_id") or event_payload.get("customer_id"),
            "workflow_id": context["workflow_id"],
            "workflow_run_id": context["run_id"],
        }
        result = store.publish_event(
            event_type=event_type,
            source=str(params.get("source") or "air.workflow"),
            payload=payload,
            idempotency_key=build_idempotency_key(
                "workflow-step-event", context["run_id"], step["id"],
            ),
            correlation_id=None,
        )
        return {"event_id": result["event_id"], "event_type": event_type,
                "duplicate": result["duplicate"]}

    if action == "notify.telegram":
        if context["execution_mode"] != "ALERT_NOTIFY":
            raise WorkflowStepError("Telegram notifications require ALERT_NOTIFY mode")
        from app.telegram_notifications import notify_candidates

        strategy = str(params.get("strategy") or "AIR_WORKFLOW").upper()
        rows = source_output.get("signals") if isinstance(source_output, dict) else None
        if not rows:
            rows = [source_output] if source_output else [event_payload]
        normalized = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            item = {**row}
            item.setdefault("signal_id", f"{context['run_id']}:{step['id']}:{index}")
            item.setdefault("customer_id", event_payload.get("customer_id"))
            normalized.append(item)
        result = asyncio.run(notify_candidates(strategy, normalized))
        return {
            "strategy": strategy, "configured": result.get("configured", False),
            "attempted": result.get("attempted", 0), "sent": result.get("sent", 0),
            "failures": result.get("failures", []),
        }

    raise WorkflowStepError(f"Unsupported workflow action: {action}")


def execute_workflow_run(store: WorkflowStore, run_id: str) -> dict[str, Any] | None:
    context = store.run_context(run_id)
    if not context:
        return None
    if context["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        return {"run_id": run_id, "status": context["status"]}
    store.set_run_status(run_id, "RUNNING")
    steps = context["workflow_spec"].get("steps", [])
    outputs: dict[str, dict] = {}
    for index, step in enumerate(steps):
        step_key = str(step["id"])
        action = str(step["action"]).lower()
        existing = store.get_run_step(run_id, step_key)
        if existing and existing["status"] in {"SUCCEEDED", "SKIPPED"}:
            if existing.get("output") is not None:
                outputs[step_key] = existing["output"]
            continue
        params = step.get("params") or {}
        max_attempts = int(step.get("max_attempts", 3))
        attempts = int(existing.get("attempts", 0)) if existing else 0
        while attempts < max_attempts:
            attempts += 1
            store.save_run_step(
                run_id=run_id, step_key=step_key, step_index=index, action=action,
                status="RUNNING", input_data=params, attempts=attempts,
            )
            try:
                output = _execute_action(store, context, step, outputs)
                store.save_run_step(
                    run_id=run_id, step_key=step_key, step_index=index, action=action,
                    status="SUCCEEDED", input_data=params, output_data=output, attempts=attempts,
                )
                outputs[step_key] = output
                break
            except Exception as exc:  # bounded retry; step actions are idempotent
                log.exception("AIR workflow step %s failed on attempt %d", step_key, attempts)
                store.save_run_step(
                    run_id=run_id, step_key=step_key, step_index=index, action=action,
                    status="FAILED", input_data=params,
                    error=f"{type(exc).__name__}: {str(exc)[:800]}", attempts=attempts,
                )
                if attempts < max_attempts:
                    time.sleep(min(2 ** (attempts - 1), 8))
        else:
            store.set_run_status(run_id, "FAILED", f"Step {step_key} exhausted {max_attempts} attempts")
            return {"run_id": run_id, "status": "FAILED", "failed_step": step_key}
    store.set_run_status(run_id, "SUCCEEDED")
    return {"run_id": run_id, "status": "SUCCEEDED", "steps": len(steps)}
