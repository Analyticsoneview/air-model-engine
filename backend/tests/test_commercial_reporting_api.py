from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.security import require_admin
import app.commercial_reporting_api as reporting_api


class FakeReportingStore:
    def report(self):
        return {
            "summary": {"total_contracts": 2, "active_contracts": 1, "invoiced_minor": 12500,
                        "refunded_minor": 0, "settled_minor": 10000},
            "invoiced_by_month": [{"month": "2026-11", "currency": "INR", "invoiced_minor": 12500}],
            "contract_plan_mix": [],
            "contract_cohorts": [],
            "usage_by_metric": [],
            "coverage": {
                "gross_margin": {"status": "UNAVAILABLE"},
                "channel_attribution": {"status": "UNAVAILABLE"},
                "retention": {"status": "CURRENT_STATUS_COHORT_PROXY"},
                "revenue_semantics": "Invoiced, refunded and settled amounts are separate ledger measures."
            }
        }


def test_commercial_reporting_is_restricted_to_admin(monkeypatch):
    client = TestClient(app)
    app.dependency_overrides[require_admin] = lambda: {"admin_id": "admin-1", "role": "ADMIN"}
    monkeypatch.setattr(reporting_api, "_store", lambda: FakeReportingStore())
    try:
        response = client.get("/api/v1/commercial/reporting/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["invoiced_minor"] == 12500
        assert payload["summary"]["settled_minor"] == 10000
        assert payload["coverage"]["gross_margin"]["status"] == "UNAVAILABLE"
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_commercial_reporting_rejects_non_admin():
    client = TestClient(app)
    app.dependency_overrides[require_admin] = lambda: {"admin_id": "support-1", "role": "SUPPORT"}
    try:
        response = client.get("/api/v1/commercial/reporting/overview")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(require_admin, None)
