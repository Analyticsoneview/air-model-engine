"""Gate 17F-9 commercial reporting over authoritative contract, usage and billing ledgers.

Amounts are reported as invoiced, refunded and settled; invoice issuance is not
misrepresented as cash collection or recognised revenue. Cost and channel data are
reported as unavailable until their source ledgers exist.
"""
from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import create_engine, text
from app.tenant_context import install_tenant_context, tenant_scope


class CommercialReportingStore:
    def __init__(self, database_url: str | None = None, engine=None):
        url = database_url or (
            Path(os.environ["AIR_CUSTOMER_DATABASE_URL_FILE"]).read_text(encoding="utf-8").strip()
            if os.getenv("AIR_CUSTOMER_DATABASE_URL_FILE")
            else os.getenv("AIR_CUSTOMER_DATABASE_URL", "").strip()
        )
        if engine is not None:
            self.engine = engine
        elif url.startswith(("postgresql://", "postgresql+psycopg://")):
            self.engine = create_engine(url, pool_pre_ping=True, future=True)
        elif url:
            raise RuntimeError("Commercial reporting requires PostgreSQL")
        else:
            raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must be configured for commercial reporting")
        install_tenant_context(self.engine)
        with self.engine.connect() as conn:
            required = ("air_commercial_contracts", "air_usage_events", "air_billing_invoices",
                        "air_billing_refunds", "air_billing_settlements", "air_billing_reconciliations")
            missing = [name for name in required if not conn.execute(
                text("SELECT to_regclass(:name)"), {"name": "public." + name}
            ).scalar()]
            if missing:
                raise RuntimeError("Commercial reporting schema is incomplete: " + ", ".join(missing))

    def _rows(self, query: str, params: dict | None = None):
        with tenant_scope(is_admin=True), self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(query), params or {}).mappings().all()]

    def summary(self):
        return self._rows("""
            SELECT
              (SELECT COUNT(*) FROM air_commercial_contracts) AS total_contracts,
              (SELECT COUNT(*) FROM air_commercial_contracts WHERE status IN ('ACTIVE','GRACE')) AS active_contracts,
              (SELECT COUNT(*) FROM air_commercial_contracts WHERE status='TRIAL') AS trial_contracts,
              (SELECT COUNT(*) FROM air_commercial_contracts WHERE status IN ('CANCELLED','EXPIRED')) AS ended_contracts,
              (SELECT COUNT(DISTINCT tenant_id) FROM air_commercial_contracts) AS customer_tenants,
              (SELECT COALESCE(SUM(total_minor),0) FROM air_billing_invoices WHERE status='ISSUED') AS invoiced_minor,
              (SELECT COALESCE(SUM(amount_minor),0) FROM air_billing_refunds) AS refunded_minor,
              (SELECT COALESCE(SUM(amount_minor),0) FROM air_billing_settlements) AS settled_minor,
              (SELECT COUNT(*) FROM air_billing_reconciliations WHERE status='MISMATCH') AS reconciliation_mismatches,
              (SELECT COUNT(*) FROM air_usage_events WHERE status='ACCEPTED') AS accepted_usage_events
        """)

    def revenue_by_month(self, limit: int = 24):
        return self._rows("""
            SELECT to_char(date_trunc('month', issued_at), 'YYYY-MM') AS month,
                   currency, COUNT(*) AS invoice_count,
                   SUM(subtotal_minor) AS subtotal_minor,
                   SUM(tax_total_minor) AS tax_minor,
                   SUM(total_minor) AS invoiced_minor
            FROM air_billing_invoices WHERE status='ISSUED' AND issued_at IS NOT NULL
            GROUP BY date_trunc('month', issued_at), currency
            ORDER BY date_trunc('month', issued_at) DESC, currency LIMIT :limit
        """, {"limit": limit})

    def plan_mix(self):
        return self._rows("""
            SELECT product_code, plan_code, currency, status, COUNT(*) AS contract_count,
                   SUM(amount_minor) AS contracted_amount_minor
            FROM air_commercial_contracts
            GROUP BY product_code, plan_code, currency, status
            ORDER BY product_code, plan_code, status
        """)

    def cohorts(self):
        return self._rows("""
            SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS cohort_month,
                   COUNT(*) AS contracts_started,
                   COUNT(*) FILTER (WHERE status IN ('ACTIVE','GRACE')) AS currently_active,
                   COUNT(*) FILTER (WHERE status IN ('CANCELLED','EXPIRED')) AS currently_ended
            FROM air_commercial_contracts
            GROUP BY date_trunc('month', created_at)
            ORDER BY date_trunc('month', created_at) DESC
        """)

    def usage_by_metric(self):
        return self._rows("""
            SELECT metric, period, unit, status, SUM(quantity) AS quantity,
                   COUNT(*) AS event_count
            FROM air_usage_events
            GROUP BY metric, period, unit, status
            ORDER BY metric, period, status
        """)

    def margin_and_channel_coverage(self):
        return {
            "gross_margin": {"status": "UNAVAILABLE", "reason": "No verified cost-of-service ledger is present; margin is not estimated."},
            "channel_attribution": {"status": "UNAVAILABLE", "reason": "No verified acquisition/channel attribution ledger is present."},
            "retention": {"status": "CURRENT_STATUS_COHORT_PROXY", "reason": "Cohorts show current contract status, not historical month-by-month retention snapshots."},
            "revenue_semantics": "Invoiced, refunded and settled amounts are separate ledger measures. They are not automatically equivalent to recognised revenue."
        }

    def report(self):
        return {
            "summary": self.summary()[0],
            "invoiced_by_month": self.revenue_by_month(),
            "contract_plan_mix": self.plan_mix(),
            "contract_cohorts": self.cohorts(),
            "usage_by_metric": self.usage_by_metric(),
            "coverage": self.margin_and_channel_coverage()
        }

    def close(self):
        self.engine.dispose()
