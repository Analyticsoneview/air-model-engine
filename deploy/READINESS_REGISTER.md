# AIR Deployment Readiness Register

This register separates **product/code delivery** from **environment-dependent deployment acceptance**. An item marked deferred is not a code failure and does not block development of the single AIR product.

Last reviewed: 2026-11-16

## Programme status

| Area | Status | Evidence / exit condition |
|---|---|---|
| Gate 14 — tenant isolation and AWS SaaS provisioning foundation | COMPLETE — CODE DELIVERY | PR #64 merged to `main`; CI validated tenant isolation, provisioning adapter behavior and Terraform configuration. No AWS resources were created. |
| Gate 15 — on-prem Compose/Swarm readiness | IN PROGRESS — CODE DELIVERY | PR #65; Compose runtime smoke is being validated in GitHub Actions. Customer-host Swarm acceptance remains deferred. |
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
| ONP-08 | Full 12-month NSE history bootstrap and application `/ready` gate | DEFERRED | Initial download complete, dataset coverage checked and `/ready` passes |
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
| PROD-01 | Tenant object-upload API wired to S3 quota enforcement | OPEN — CODE WORK | API-level authorization, quota enforcement, object lifecycle and tests |
| PROD-02 | Deployment Manager installation/readiness consistency across Windows/Linux | IN PROGRESS | Same profile validation, secret handling, service health and failure reporting |
| PROD-03 | Initial NSE/CM/FO data bootstrap idempotency and resume behavior | OPEN — CODE WORK | Automated tests for partial download, retry, integrity and restart |
| PROD-04 | Deployment readiness report in the application/installer | OPEN — CODE WORK | Clear distinction between infrastructure, service health, data readiness and user onboarding |

## Programme rules

1. Continue code implementation and CI acceptance without waiting for an AWS account or customer host.
2. Do not apply Terraform, create cloud resources, run production migrations or incur cloud cost without an explicit deployment approval.
3. Do not mark an environment-dependent item complete from static tests or mocked AWS tests.
4. A CI runtime smoke is evidence of container boot and service connectivity only; it is not a customer-host production deployment.
5. Keep deferred items visible and execute them when the required environment becomes available.
