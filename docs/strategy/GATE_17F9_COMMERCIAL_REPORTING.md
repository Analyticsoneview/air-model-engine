# Gate 17F-9 — Commercial reporting

**Status:** IN PROGRESS — PR validation required  
**Branch:** `gate17f9/commercial-reporting`  
**Base:** `main` at `3a45b9b898f0c28aeaeb43d084b75bf52d328d34`

## Objective

Provide an administrator-only commercial reporting surface over the existing contract, usage, invoice, refund, settlement and reconciliation ledgers. Do not create a parallel financial ledger.

## Implemented in this slice

- Read-only reporting queries over `air_commercial_contracts`, `air_usage_events`, `air_billing_invoices`, `air_billing_refunds`, `air_billing_settlements` and `air_billing_reconciliations`.
- Summary counts for contracts, active/trial/ended contracts, tenant count, issued invoice value, refunds, settlements, reconciliation mismatches and accepted usage events.
- Monthly issued-invoice totals grouped by currency.
- Contract/product/plan/status mix.
- Contract-start cohorts with current active/ended status.
- Usage totals by metric, period, unit and status.
- Administrator-only endpoint: `GET /api/v1/commercial/reporting/overview`.
- Tenant RLS is accessed under an explicit server-side admin reporting context; callers cannot supply tenant IDs or SQL filters.

## Financial semantics and limitations

- Issued invoices are reported as **invoiced**, not as cash collected or recognised revenue.
- Settlements and refunds are separate measures. They are not assumed to reconcile one-to-one with invoices without a settlement allocation ledger.
- Current contract state is a cohort proxy, not historical month-by-month retention.
- Gross margin is explicitly unavailable because a verified cost-of-service ledger is not present.
- Channel attribution is explicitly unavailable because no verified acquisition attribution ledger is present.
- No payment collection, refunds, settlement ingestion, price publication or customer-facing financial data is enabled by this reporting slice.

## Acceptance still required

- Full backend unit and pytest suites.
- PostgreSQL integration using disposable services and the existing migrations.
- Tenant/RLS isolation and administrator authorization tests.
- Currency grouping, date boundaries, idempotent ledger source behavior and empty-ledger behavior.
- On-prem Compose and release-package regression.
- Exact-head green CI before merge.

## Non-goals

No new financial source-of-truth tables, no fabricated margin/CAC/LTV, no automatic accounting recognition policy, no payment provider changes, and no AWS resource provisioning.
