import os
import re
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.model_engine_ledger import ModelEngineLedger
from app.portfolio_risk import PortfolioRiskStore, build_portfolio_snapshot
from app.account_reporting import AccountReporting


_DATABASE_CONFIGURED = bool(
    (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_DATABASE_URL"))
    and (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_DATABASE_URL"))
    and (os.getenv("AIR_CUSTOMER_DATABASE_URL") or os.getenv("AIR_DATABASE_URL"))
)


@pytest.mark.skipif(not _DATABASE_CONFIGURED, reason="requires disposable PostgreSQL integration workflow")
def test_portfolio_snapshots_and_model_signals_use_postgres_with_customer_isolation():
    customer_a = "portfolio-test-" + uuid4().hex
    customer_b = "portfolio-test-" + uuid4().hex
    snapshot_store = PortfolioRiskStore()
    ledger = ModelEngineLedger()
    try:
        snapshot = build_portfolio_snapshot({
            "positions": [{"symbol": "NIFTY", "quantity": 2, "average_price": 100, "last_price": 110}],
            "holdings": [],
        }, "dhan", "test-account")
        snapshot_store.save(customer_a, snapshot)
        assert snapshot_store.overview(customer_a)["account_count"] == 1
        assert snapshot_store.overview(customer_b)["account_count"] == 0

        signal_id = "PORTFOLIO-POSTGRES-" + uuid4().hex
        ledger.upsert(customer_a, {
            "signal_id": signal_id, "classification": "NEW",
            "signal_date": "2026-11-15", "symbol": "NIFTY",
            "entry_price": 100, "latest_price": 110,
            "evidence": {"source": "integration-test"},
        })
        # Reusing a global signal key from another tenant must not overwrite or
        # expose the first tenant's record.
        ledger.upsert(customer_b, {
            "signal_id": signal_id, "classification": "HOLD",
            "signal_date": "2026-11-15", "symbol": "NIFTY",
            "entry_price": 100, "latest_price": 999,
            "evidence": {"source": "cross-tenant-attempt"},
        })
        assert ledger.list_signals(customer_a)[0]["latest_price"] == 110
        assert ledger.list_signals(customer_b) == []
    finally:
        snapshot_store.db.execute("DELETE FROM air_portfolio_snapshots WHERE customer_id IN (?,?)",
                                  (customer_a, customer_b))
        ledger.db.execute("DELETE FROM model_signals WHERE customer_id IN (?,?)",
                          (customer_a, customer_b))
        snapshot_store.close()
        ledger.close()

@pytest.mark.skipif(not _DATABASE_CONFIGURED, reason="requires disposable PostgreSQL integration workflow")
def test_account_report_verification_and_history_use_postgres():
    customer = "report-test-" + uuid4().hex
    reports = AccountReporting()
    sent = []
    try:
        with patch.object(AccountReporting, "_send_email",
                          side_effect=lambda recipient, subject, body, attachments=None: sent.append(body)):
            reports.request_verification(customer, "reports@example.com")
        code_match = re.search(r"code is (\d{6})", sent[0])
        assert code_match
        verified = reports.confirm_verification(customer, code_match.group(1))
        assert verified["verified"] in (1, True)
        reports.db.execute("""INSERT INTO account_report_runs
            (customer_id,broker,account_id,report_date,status,detail)
            VALUES(?,?,?,?,?,?)""",
            (customer, "dhan", "integration-account", "2026-11-15", "SENT", None))
        history = reports.history(customer)
        assert len(history) == 1
        assert history[0]["status"] == "SENT"
    finally:
        reports.db.execute("DELETE FROM account_report_runs WHERE customer_id=?", (customer,))
        reports.db.execute("DELETE FROM report_recipients WHERE customer_id=?", (customer,))
        reports.close()
