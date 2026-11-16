# AIR Global Implementation Programme

**Status:** FROZEN PROGRAMME BASELINE — 17 November 2026  
**Parent strategy:** [AIR Global Strategic Master Plan](AIR_GLOBAL_MASTER_STRATEGY.md)  
**Repository:** `Analyticsoneview/air-model-engine`  
**Programme type:** Stage-gated product, commercial and global expansion roadmap.

## 1. Programme purpose

Translate the AIR global strategic ambition into an executable repository programme without replacing existing services or claiming unfinished capabilities. The programme extends the current AIR codebase through small, reviewable, test-backed pull requests.

The programme does not authorise paid regulated research, personalised investment advice, unattended broker execution, exchange-data redistribution or cloud-resource creation. Those require their own approvals.

## 2. Verified repository baseline at programme creation

The baseline was inspected on the repository default branch `main` on 17 November 2026.

- The repository README describes AIR as a self-hosted research/broker-connectivity foundation with Flutter client and FastAPI backend; it explicitly says it is not yet a production trading system.
- Existing foundations include PostgreSQL, Redis, RabbitMQ, workflow engine, deployment manager, on-premises and AWS deployment profiles, tenant object-storage API, broker connectivity foundations and research screens.
- The workflow engine uses PostgreSQL as durable system of record and RabbitMQ for initial task/event transport; it is designed to orchestrate existing domain services, not duplicate calculations.
- `backend/app/subscription_access.py` provides a basic active-subscription gate for strategy APIs. `backend/app/access_control.py` includes customer subscriptions, plan history, lifecycle and promotional-consent foundations.
- `mobile/lib/screens/air_subscription_screen.dart` loads plans and subscription status, but explicitly states online payments and automatic renewals are not enabled and public pricing will be added before payments go live.
- Tenant object storage is documented for the SaaS multi-tenant profile; live AWS acceptance remains environment-dependent.
- Main-branch deployment readiness documentation still identifies initial market-data bootstrap, readiness integration and complete monitoring as open/deferred work. Multi-exchange data readiness must be proven per segment.
- PRs #73, #74 and #75 were open at the time of inspection. PR #75 head `d338944fc587142240885d7993ad2dc3f37859a4` had four successful workflow runs: PR validation, RabbitMQ integration, PostgreSQL recovery acceptance and deployment-profile/AWS Terraform acceptance. Passing CI does not mean PR #75 or its parent PRs are merged.
- Existing docs and feature branches must be reconciled with current main before implementation. Do not assume an open PR's code is available on main.

This is a point-in-time baseline. Re-check main, open PRs, workflow runs and changed files before each implementation gate.

## 3. Programme dependency rules

1. Continue existing release programme work: multi-exchange data bootstrap/recovery, readiness, monitoring and release certification.
2. Complete and merge the SEBI compliance framework and owner-only internal workspace slices only after their own required CI, review and dependency checks.
3. Gate 17E remains a mandatory release gate for applicable external research/advisory features; it cannot be bypassed by a pricing or product tier.
4. Gate 17F commercial planning and foundational catalogue work may proceed in parallel, but paid launch and regulated feature activation remain blocked until legal, provider and operational prerequisites pass.
5. Subscription entitlements must be enforced server-side; client-side hiding is not access control.
6. No production payment, live AWS resource, customer migration or paid data feed is activated without explicit environment, budget, provider and operational approval.
7. Every PR must state exact scope, dependencies, tests, non-goals and evidence. Do not merge on assumed or pending CI.

## 4. Workstream architecture

| Workstream | Scope | Shared platform dependency |
|---|---|---|
| P1 Identity and organisations | Individual users, organisations, tenants, memberships, roles, SSO/MFA | Identity and tenant service |
| P2 Commercial catalogue | Plans, modules, feature flags, quotas, regions and contract entitlements | Entitlement service |
| P3 Billing and payments | Checkout, payment intents, webhook verification, invoices, refunds, tax and renewals | Billing ledger |
| P4 Usage metering | API, compute, storage, seats, data and workflow usage | Metering and cost attribution |
| P5 Customer lifecycle | Trials, activation, suspension, cancellation, renewal, dunning and support | Customer lifecycle |
| P6 B2B administration | Workspaces, seat provisioning, role policies, audit, SSO and contract controls | Organisation/tenant service |
| P7 Data fabric | Exchange/provider adapters, canonical instruments, calendars, provenance, licensing and quality | Market data foundation |
| P8 Research platform | Screeners, charting, options, QOC, backtests, portfolio and risk | Research engine |
| P9 Quant compute | Job queue, compute quotas, cancellation, reproducibility and usage billing | Workflow + metering |
| P10 Developer/partner platform | API keys, OAuth clients, scopes, rate limits, SDKs, webhooks and partner contracts | API gateway/entitlements |
| P11 Embedded/white-label | Branding, configuration, tenant isolation, partner reporting and revenue-share ledger | Tenant + partner services |
| P12 Deployment fabric | On-prem, private, SaaS, region-specific provisioning and upgrades | Deployment Manager |
| P13 Global operations | Currency, tax, localisation, time zones, calendars, privacy and residency | Regional configuration |
| P14 Trust and governance | Security, privacy, model governance, legal applicability, data rights and audit | Governance services |
| P15 Commercial intelligence | Revenue, cohorts, CAC, LTV, churn, NRR, margins and product adoption | Analytics warehouse/reporting |

## 5. Gate sequence

### Gate 17F — Commercial product foundation

**Purpose:** Turn existing subscription/access foundations into a governed commercial product model.

| Slice | Deliverable | Acceptance evidence |
|---|---|---|
| 17F-0 | Strategy and product catalogue baseline | Approved product/plan/module definitions and decision record |
| 17F-1 | Server-side plan, module and feature-entitlement catalogue | Versioned catalogue; deny-by-default unknown features; unit/integration tests |
| 17F-2 | Subscription lifecycle and contract ledger | Trial, active, grace, past-due, cancelled, expired and suspended states; idempotent transitions |
| 17F-3 | Usage metering and quotas | Auditable usage events, aggregation, idempotency, limits and overage policy |
| 17F-4 | Payment provider abstraction | Provider adapter contract, sandbox tests, verified webhook signatures, replay protection; no live charging by default |
| 17F-5 | Invoices, tax and refunds | Immutable billing records, currency precision, tax configuration, credit/refund reconciliation |
| 17F-6 | Customer onboarding and lifecycle | Trial activation, consent, verification, renewal notices, cancellation and support workflows |
| 17F-7 | B2B organisation and seat administration | Tenant/member isolation, roles, seat allocation, audit and contract entitlements |
| 17F-8 | Enterprise licence and deployment activation | Signed/verified licence payload, offline/online activation policy, expiry/grace and revocation |
| 17F-9 | Commercial reporting | Revenue, cohorts, retention, usage, margin and channel attribution; reconcile to billing ledger |
| 17F-10 | Commercial release readiness | Legal, tax, payment, data licence, support, security and rollback evidence |

**Important design:** Use a provider-neutral payment interface. Select a payment provider only after target countries, currencies, merchant eligibility, fees, recurring-payment support, refunds, tax and settlement requirements are assessed. Never store card data. Verify signed webhooks, enforce idempotency and reconcile provider settlements to the internal ledger.

### Gate 18 — Release certification

Retain the existing Gate 18 role as a full technical and operational release gate. Include regression of the commercial foundation, deployment readiness, data bootstrap, backup/restore, monitoring, security and customer-host acceptance. A green CI run alone is not production acceptance.

### Gate 19 — Unified global data fabric

- Canonical instrument and venue model.
- Exchange/segment adapter SDK and contract tests.
- India coverage completion and source-vs-store reconciliation.
- US market adapters and corporate actions subject to provider rights.
- Market calendar, timezone, currency and session services.
- Data entitlement registry and display/redistribution enforcement.
- Historical and real-time data quality, freshness and lineage.
- Per-market readiness and coverage dashboard.

**Exit:** Every enabled market/segment has documented source rights, parser tests, coverage metrics, reconciliation, recovery and readiness. Unsupported segments remain explicitly blocked.

### Gate 20 — Research platform integration

- Common research contracts and methodology registry.
- Screener, charting, derivatives and options analytics integration.
- AIR QOC and other methodologies with versioned evidence lineage.
- Historical backtesting, walk-forward and out-of-sample validation.
- Paper research and simulation.
- Portfolio and risk analytics.
- Reproducible research reports and audit records.

**Exit:** Results are reproducible from versioned data/methodology inputs; limitations and data coverage are visible. No performance guarantee or unverified signal claim.

### Gate 21 — Quant compute and workflow scale

- Durable compute job service, quotas and fair scheduling.
- Parallel backtest/optimisation workers.
- Cancellation, timeout, retry and idempotency.
- Compute usage metering and cost attribution.
- Worker isolation and resource limits.
- Workflow templates and event catalogue.
- Load, failure-injection and recovery acceptance.

RabbitMQ remains the initial task transport. Evaluate Kafka only if measured throughput, retention/replay and multi-consumer requirements justify its operational cost. No technology is added for marketing purposes.

### Gate 22 — Developer and partner platform

- API gateway and versioned API contracts.
- API credentials/OAuth clients, scoped permissions and rotation.
- Rate limits, quotas, usage metering and billing.
- Python, JavaScript/TypeScript, Java and Go SDKs.
- Webhooks with signatures, retries and delivery logs.
- Sandbox and developer documentation.
- Partner onboarding, approval, revocation and support.
- Integration marketplace governance.

**Exit:** External developers can build a supported integration without direct database access or bypassing customer entitlements.

### Gate 23 — Institutional and embedded platform

- Organisation workspaces and multi-user collaboration.
- SSO/MFA, role-based controls and audit export.
- Enterprise data boundary and private deployment.
- White-label branding and configurable modules.
- Partner provisioning and tenant lifecycle.
- Contract, seat, API and usage reconciliation.
- SLA, support and incident-management process.

**Exit:** At least one controlled pilot per target customer archetype passes security, isolation, usage, support and contractual acceptance.

### Gate 24 — Global commercial operations

- Multi-currency price book and FX handling.
- Country-specific tax, invoices and payment methods.
- Localised onboarding, terms, privacy and support.
- Regional data residency and retention policies.
- Market calendars, time zones and holiday rules.
- Local legal and regulatory approvals.
- Regional incident response and business continuity.

**Exit:** Country/region launch checklist signed by legal, finance, security, data partners and operations. No automatic country activation.

### Gate 25 — Global scale and ecosystem

- Partner-led distribution and enterprise channel operations.
- Marketplace revenue and partner settlement.
- Usage-based data/API/compute product expansion.
- Multi-region control plane and operational resilience.
- Strategic alliances and acquisition integration readiness.
- Independent market sizing and revalidation of stretch targets.

**Exit:** Revenue concentration, gross margin, reliability, customer retention and compliance are acceptable at each expansion step.

## 6. Financial milestone control framework

Track annual revenue milestones separately for B2C and B2B:

| Stage | B2C annual checkpoint | B2B annual checkpoint |
|---|---:|---:|
| Validation | ₹1–10 Cr | ₹1–10 Cr |
| Product-market fit | ₹25–100 Cr | ₹25–100 Cr |
| National scale | ₹250–1,000 Cr | ₹250–1,000 Cr |
| International expansion | ₹1,000–3,000 Cr | ₹1,000–5,000 Cr |
| Global scale | ₹3,000–10,000 Cr | ₹5,000–25,000 Cr |
| Extreme stretch | ₹10,000 Cr | Up to ₹1,00,000 Cr |

These are stage checkpoints, not date commitments or forecasts. A stage is not passed merely because revenue is booked once. Require retention, gross margin, customer concentration, cash collection, support capacity, security and compliance evidence.

### Minimum management dashboard

- Recognised revenue, ARR/MRR, billings and deferred revenue.
- B2C paid users, free-to-paid conversion, ARPU, cohort retention and churn.
- CAC, LTV, payback, refunds and contribution margin.
- B2B pipeline, ACV, win rate, sales cycle, renewals and net revenue retention.
- Revenue and gross margin by region, product, channel and deployment model.
- API/compute/data usage, unit cost, quota breaches and overage revenue.
- Availability, latency, data freshness, job success and recovery.
- Security, privacy, compliance and licence evidence status.

## 7. Release and acceptance rules

Every gate must include:
1. Scope and explicit non-goals.
2. Dependency and migration plan.
3. API/schema contracts and backward compatibility.
4. Unit, integration, security and failure/recovery tests appropriate to the change.
5. Tenant/owner isolation tests where applicable.
6. Observability, audit and support runbook.
7. Deployment profile coverage: local/Compose and Swarm; SaaS-specific tests only where applicable.
8. Cost and data-licensing implications.
9. Rollback and data-recovery plan.
10. CI evidence linked to the exact commit SHA.

No PR is merged while required checks fail or are pending. Do not use test deletion, broad skips, weakened assertions or mock-only tests to claim acceptance. Separate CI validation from live environment acceptance.

## 8. Initial execution order

1. Reconcile and complete current open PRs and programme dependencies; recheck current main and CI.
2. Complete the active market-data/bootstrap, readiness and monitoring release dependencies.
3. Close Gate 17E compliance framework and owner-only workspace slices under their existing dependency chain.
4. Create Gate 17F-0 product catalogue and feature entitlement decision record.
5. Implement Gate 17F-1 server-side entitlements before exposing commercial purchase actions.
6. Implement subscription lifecycle and usage metering before payment collection.
7. Implement payment sandbox, webhook verification, invoice/refund reconciliation and tax configuration.
8. Implement B2B organisations, seats, enterprise licences and admin controls.
9. Add developer/partner and embedded services after stable API contracts and entitlement enforcement.
10. Enter global markets only after regional data, legal, privacy, tax, payments and support readiness.

## 9. Programme governance

- One master strategy and one programme ledger; no parallel product forks.
- Every gate uses a dedicated branch and reviewable PR, stacked only where a real dependency exists.
- Keep main releasable; avoid bundling unrelated gates.
- Publish status as NOT STARTED / IN PROGRESS / BLOCKED / CI PASSED / MERGED / ENVIRONMENT ACCEPTED.
- Record evidence URL, commit SHA, owner, dependencies and unresolved risks.
- Update this programme only through a versioned decision record.
- Do not change frozen annual targets without a documented strategy review.

## 10. Immediate next gate

**Gate 17F-0 — Product catalogue and commercial entitlement baseline.**

First inspect and reuse the existing subscription plan API, `AccessStore`, PostgreSQL customer-auth store, operator lifecycle tools and customer subscription screen. Define a canonical catalogue and entitlement contract before changing database schemas or adding payment providers.

The first implementation PR should deliver:
- B2C/B2B product and plan catalogue schema.
- Versioned feature and quota definitions.
- Server-side entitlement resolution contract.
- Plan-to-feature matrix and migration compatibility.
- Tests for unknown plan, expired subscription, suspended customer, tenant mismatch, feature downgrade and operator override.
- Documentation of what is not yet purchasable.

It must not activate live payments or paid regulated research. Gate 17F-0 is a strategy and contract baseline; later slices implement the operational systems.
