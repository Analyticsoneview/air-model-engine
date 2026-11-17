#!/usr/bin/env python3
"""Exit zero only when the workflow runtime has a fresh RabbitMQ-connected heartbeat."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.installation_readiness import evaluate_workflow_runtime
from app.workflow_engine import WorkflowStore

def main() -> int:
    store = WorkflowStore()
    try:
        report = evaluate_workflow_runtime(store.list_worker_heartbeats(100))
    finally:
        store.close()
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("healthy") else 2

if __name__ == "__main__":
    raise SystemExit(main())
