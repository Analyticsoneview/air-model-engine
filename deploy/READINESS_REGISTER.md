# AIR Deployment Readiness Register

This register separates **product/code delivery** from **environment-dependent deployment acceptance**. An item marked deferred is not a code failure and does not block development of the single AIR product.

Last reviewed: 2026-11-17

## Programme status

| Area | Status | Evidence / exit condition |
|---|---|---|
| Gate 14 — tenant isolation and AWS SaaS provisioning foundation | COMPLETE — CODE DELIVERY | PR #64 merged to `main`; CI validated tenant isolation, provisioning adapter behavior and Terraform configuration. No AWS resources were created. |
| Gate 15 — on-prem Compose/Swarm readiness | COMPLETE — CODE DELIVERY | PR #65 merged to `main`; ephemeral Compose runtime boot, service health and RabbitMQ-connected worker heartbeat passed CI. Customer-host Swarm acceptance remains deferred. |
| Gate 16 — Deployment Manager and release packaging | COMPLETE — CODE DELIVERY | PR #69 merged to `main`; cross-platform manager, on-prem install/upgrade, diagnostics, secret-free source bundle and checksummed runtime image artifact. AWS/customer-host deployment remains deferred. |
| Gate 17A — tenant object storage API and quota enforcement | COMPLETE — PR #71 MERGED | Authenticated upload/list/download, PostgreSQL transactional quota ledger, retry-safe reservations, S3 body-digest verification, download integrity checks and registry-level tenant membership/role enforcement; PR #71 merged as `cee615308b2667ec959d47a88694508dbe4ab399`; all required CI checks passed. Live AWS/S3 acceptance remains deferred. |
| Gate 17B — multi-exchange market-data bootstrap and recovery | IN PROGRESS — BRANCH `gate17b/nse-bootstrap-recovery-hardening` | Full enabled-source ingestion is independent of strategy universes: NSE CM/FO/CD/COM, BSE CM/FO/CD/CO, MCX and NCDEX; plus a separate global-markets domain targeting Nasdaq, NYSE, eligible NYSE Arca/other US venues and NSE IX/GIFT City US-stock receipts. Add licensed-provider EOD/reference data, corporate actions, US calendars, USD-native prices, separate FX observations and broker-specific global-access catalogues. PR #72 is the first NSE archive-recovery hardening slice; it does not complete multi-exchange or US adapters. US venues remain BLOCKED/DEFERRED until provider coverage, commercial rights, credentials and history depth are verified. |
| Gate 17C — deployment readiness report | PLANNED | One readiness contract separates infrastructure, service health, data coverage and customer onboarding. |
| Gate 17D — on-prem monitoring integration | PLANNED | Prometheus scrape targets, Grafana dashboards, alert rules and Compose/Swarm runtime acceptance. |
| Gate 18 — final release certification | PLANNED | Full backend/PostgreSQL/Redis/RabbitMQ, Android/PWA, migration, security and deployment regression; no AWS/customer-host completion claims without live evidence. |
| AWS live infrastructure | DEFERRED — ENVIRONMENT NOT AVAILABLE | No AWS account, credentials, region, remote state or budget approval has been supplied. |
| Production on-prem installation | DEFERRED — CUSTOMER HOST NOT AVAILABLE | No target customer host is connected for installation and operational acceptance. |
| Initial market-data bootstrap | DEFERRED — INSTALLATION ACCEPTANCE | Must be verified during first installation; CI smoke intentionally skips the 12-month NSE history download. |

## On-premises deployment acceptance

| ID | Activity | Status | Completion evidence |
|---|---|---|---|
| ONP-01 | Compose profile and secret/config rendering | CI VALIDATED | GitHub Actions Compose config acceptance |
| ONP-02 | Compose PostgreSQL, Redis, RabbitMQ, API, worker and PWA runtime | CI VALIDATED | Ephemeral runner boot, API/PWA health and RabbitMQ-connected worker heartbeat |
| ONP-03 | Docker Swarm stack rendering and external-secret contract | CI VALIDATED | `docker stack config` and regression tests |
| ONP-04 | Install on a representative customer Windows/Linux host | DEFERRED | Successful one-click installation on the target host |
| ONP-05 | Swarm service deployment, placement, restart and node recovery on target host | DEFERRED | Live Swarm acceptance report |
| ONP-06 | DNS, TLS certificate issuance/renewal and external access | DEFERRED | Verified customer-domain HTTPS and renewal test |
| ONP-07 | Persistent-volume backup and restore drill | DEFERRED | Successful restore with integrity checks |
| ONP-08 | Full configured market history bootstrap (India segments plus approved global-market providers) and application `/ready` gate | DEFERRED | Initial downloads complete for every enabled/licensed scope, per-market coverage reconciled and `/ready` passes; blocked/unlicensed scopes remain explicitly visible |
| ONP-09 | Broker connection, customer onboarding and QOC readiness smoke | DEFERRED | Authorized test account and end-to-end operational acceptance |

## AWS deployment acceptance

| ID | Activity | Status | Completion evidence |
|---|---|---|---|
| AWS-01 | AWS account, region, deployment role and cost approval | DEFERRED | Authorized account and approved budget |
| AWS-02 | Encrypted Terraform remote state and locking | DEFERRED | Backend configured, access reviewed and lock tested |
| AWS-03 | Terraform plan/security review and approved apply | DEFERRED | Reviewed plan and recorded apply result |
| AWS-04 | ECR images, ACM certificate and ECS service rollout | DEFERRED | Immutable image digests deployed; ALB/API/PWA health verified |
| AWS-05 | Database migration, rollback and recovery acceptance | DEFERRED | Approved migration report and tested recovery procedure |
| AWS-06 | SaaS tenant provisioning against live S3, RabbitMQ and Secrets Manager | DEFERRED | Test tenant provision/suspend/reactivate verified in AWS |
| AWS-07 | Tenant isolation, quota, IAM and network penetration checks | DEFERRED | Live cross-tenant denial, quota and least-privilege evidence |
| AWS-08 | Production monitoring, backup, restore and incident runbooks | DEFERRED | Operational handover and recovery drill |

## Product code items that remain independent of AWS

| ID | Activity | Status | Completion evidence |
|---|---|---|---|
| PROD-01 | Tenant object-upload API wired to S3 quota enforcement | COMPLETE — GATE 17A / PR #71 | Tenant-authenticated upload/list/download, transactional quota reservations, immutable keys, retry recovery, SHA-256 integrity and API/PostgreSQL tests; live AWS acceptance remains deferred |
| PROD-02 | Deployment Manager installation/readiness consistency across Windows/Linux | COMPLETE — GATE 16 / PR #69 | Shared CLI actions, Windows/Linux wrappers, upgrade flow, status and diagnostic reporting; CI release artifacts verified |
| PROD-03 | Multi-exchange historical market-data bootstrap and recovery | IN PROGRESS — GATE 17B | Download all available instruments/contracts from each enabled exchange/segment and licensed global-market provider; cover NSE/BSE/MCX/NCDEX plus US venues and NSE IX receipts; separate canonical ingestion catalogues from Nifty 500 and broker-specific research/access universes; validate source-specific archive integrity, session coverage, complete masters, corporate actions, FX provenance, licensing/entitlements, atomic recovery and per-market readiness |
| PROD-04 | Deployment readiness report in the application/installer | OPEN — CODE WORK | Clear distinction between infrastructure, service health, data readiness and user onboarding |
| PROD-05 | On-prem Grafana/Prometheus runtime integration | OPEN — CODE WORK | The profile declares `grafana_prometheus`, but Compose/Swarm do not yet ship a complete metrics/Grafana service set; do not claim monitoring is production-ready until implemented and tested |

## Programme rules

1. Continue code implementation and CI acceptance without waiting for an AWS account or customer host.
2. Do not apply Terraform, create cloud resources, run production migrations or incur cloud cost without an explicit deployment approval.
3. Do not mark an environment-dependent item complete from static tests or mocked AWS tests.
4. A CI runtime smoke is evidence of container boot and service connectivity only; it is not a customer-host production deployment.
5. Keep deferred items visible and execute them when the required environment becomes available.


## Gate 17B — expanded market-data coverage register

| Scope ID | Market/data scope | Status | Exit evidence |
|---|---|---|---|
| G17B-IN-01 | NSE CM/FO/CD/COM and BSE CM/FO/CD/CO | IN PROGRESS | Source-specific adapters, calendars, complete security/contract masters, EOD history, reconciliation, recovery and CI per enabled segment |
| G17B-CMD-01 | MCX and NCDEX commodity derivatives | IN PROGRESS — SOURCE VALIDATION REQUIRED | Official-source access/history/schema verified; complete contract catalogue, EOD backfill, session reconciliation and restart tests |
| G17B-US-01 | Nasdaq and NYSE listed equities/ETFs | BLOCKED / DEFERRED — PROVIDER & LICENCE NOT SELECTED | Approved provider agreement and credentials; documented venue/instrument coverage, history depth, permitted storage/display/derived use, EOD adapter and CI acceptance |
| G17B-US-02 | NYSE Arca and other US venues | BLOCKED / DEFERRED — COVERAGE TO VERIFY | Explicit venue allow-list and provider coverage/licence evidence; independent readiness and acceptance |
| G17B-GIFT-01 | NSE IX / GIFT City US-stock receipts | BLOCKED / DEFERRED — SOURCE & INSTRUMENT MASTER VALIDATION | Official NSE IX source and instrument definitions verified; distinct receipt identity, underlying mapping, ratio/corporate actions and EOD history tests |
| G17B-BRK-01 | Indian brokers' US/global-investing access catalogues | PLANNED — BROKER CONNECTOR DEPENDENT | Broker-specific catalogue with account eligibility, tradability restrictions, effective dates and refresh evidence; never used as exchange-wide master |

### Global-market controls

- US EOD/reference data, delayed data and live feeds are separate entitlements and readiness scopes.
- Native USD prices and USD/INR observations remain separate; INR valuation is derived and timestamped.
- US trading calendars use the venue's local timezone and daylight-saving rules.
- US-listed underlying shares and NSE IX receipts are distinct instruments and must not have their price/volume/liquidity histories merged.
- Broker access is a tradability overlay, not a source of truth for exchange-wide market coverage.
- No US market scope may be marked READY until commercial data rights and actual provider coverage are verified. Mock/sandbox tests do not constitute live-market acceptance.
