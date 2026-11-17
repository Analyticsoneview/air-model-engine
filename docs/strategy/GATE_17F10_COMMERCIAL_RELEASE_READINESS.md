# Gate 17F-10 — Commercial release readiness

**Status:** BLOCKED — evidence collection and control validation only  
**Branch:** `gate17f10/commercial-release-readiness`  
**Base:** `main` at `c3ce664a301bd45833fdc39193cd781482935917`  
**Decision:** No paid commercial launch, public price publication, live payment collection, paid data-feed activation or regulated research distribution is authorised by this gate.

## 1. Purpose and release boundary

Gate 17F-10 is the final commercial release-readiness assessment for the Gate 17F catalogue, contract, metering, payment-sandbox, invoice/reconciliation, onboarding, organisation/seat and enterprise-licensing capabilities.

It must distinguish:
- **Code delivery:** implementation and automated tests are complete.
- **Operational readiness:** deployment, support, recovery and monitoring have been exercised in the target environment.
- **Legal/provider readiness:** written approvals, contractual rights and provider eligibility are verified for the exact entity, countries, products and customer journey.
- **Launch authorization:** accountable legal/compliance, finance, security and operations owners sign the exact release scope.

A green CI pipeline proves code acceptance only; it does not prove the latter three categories.

## 2. Current evidence assessment

| Control area | Current evidence | Gate 17F-10 assessment | Evidence required to exit |
|---|---|---|---|
| Product catalogue and entitlement contract | Gate 17F-0/17F-1 catalogue and entitlement contract exists on main | CODE PRESENT; commercial activation restricted | Signed product/plan/feature matrix, price approval and entitlement regression |
| Contract lifecycle | Gate 17F-2 contract ledger and transition history | CODE PRESENT; operational review required | PostgreSQL tenant-isolation evidence, lifecycle reconciliation and support runbook |
| Usage and quotas | Gate 17F-3 usage events, counters and quota enforcement | CODE PRESENT; billing linkage review required | Meter-to-contract reconciliation, quota boundary and adjustment audit |
| Payment provider | Gate 17F-4 offline sandbox and signed webhook receipt ledger | SANDBOX ONLY; no live provider | Provider due diligence, merchant onboarding, live webhook/replay tests and written approval |
| Invoices, tax, refunds and settlement | Gate 17F-5 invoice/credit-note/settlement/reconciliation ledger | CODE PRESENT; tax rules not configured/approved for a launch jurisdiction | Jurisdiction-specific tax opinion/configuration, invoice format approval, refund and settlement operating procedures |
| Customer onboarding | Gate 17F-6 lifecycle/onboarding capabilities | CODE PRESENT; live support process not evidenced | Identity, communications, complaint handling, account recovery and offboarding acceptance |
| B2B organisations and seats | Gate 17F-7 organisation, membership and seat controls | CODE PRESENT; customer-host acceptance outstanding | Owner/admin/member isolation tests and operational seat administration runbook |
| Enterprise licensing | Gate 17F-8 signed offline licence and deployment binding | CODE PRESENT; disconnected revocation has documented limits | Key custody ceremony, issuance/revocation runbook, recovery and customer deployment acceptance |
| Commercial reporting | Gate 17F-9 ledger-backed admin reporting | MERGED; reporting semantics are deliberately limited | Finance review of definitions and reconciliations; gross margin/channel attribution remain unavailable |
| Legal and regulatory | Compliance framework exists in `compliance/SEBI_COMPLIANCE_CONTROL_FRAMEWORK.md` | NOT SIGNED / BLOCKING | Current written counsel applicability opinion and authorised compliance sign-off |
| Market-data rights | Market-data bootstrap and provider scope tracked separately | NOT VERIFIED FOR COMMERCIAL DISTRIBUTION | Provider/exchange agreements, permitted use, derived-data and redistribution rights per market |
| Security and privacy | Security controls and automated tests exist | CODE EVIDENCE ONLY | Independent security review, privacy notice/retention assessment, incident response and vulnerability disposition |
| Support and operations | Support centre code exists | OPERATIONAL ACCEPTANCE NOT EVIDENCED | Named support owner, SLA, escalation, complaint/refund workflow, incident and business-continuity drills |
| Deployment and recovery | Compose/Swarm CI and PostgreSQL recovery CI exist | CI VALIDATED; customer-host acceptance deferred | Representative on-prem install, backup/restore, monitoring and upgrade/rollback evidence |
| AWS/SaaS environment | Terraform and deployment profile validation only | DEFERRED — no AWS account/credentials/budget approval | Explicit environment, security, budget and provisioning approval before live AWS use |

## 3. Mandatory release blockers

The following are hard blockers for any paid external launch:

1. **Legal entity and jurisdiction:** identify the contracting entity, launch countries/states, customer types and permitted commercial activities.
2. **Written legal/compliance opinion:** determine software, research, investment-advice, broker/API/algo and consumer obligations for the exact product and customer journey. Gate 17E remains a mandatory separate release gate for regulated research/advisory features.
3. **Market-data rights:** verify each exchange/vendor contract permits the exact collection, storage, derived analytics, customer display, redistribution and commercial use. A technical adapter or public download URL is not a licence.
4. **Tax and invoicing:** obtain jurisdiction-specific tax advice and configure approved tax codes, invoice/credit-note content, numbering, retention and filing responsibilities.
5. **Payment provider approval:** complete merchant onboarding, settlement account verification, provider contract, supported payment methods, recurring-payment/refund/chargeback controls and live webhook security. Existing sandbox code is not a production payment integration.
6. **Security/privacy:** complete threat model, independent penetration/security review, privacy notice and data-retention review, secrets/key custody, incident response and breach escalation.
7. **Customer operations:** define support hours, service levels, complaints/grievances, refund authority, account recovery, cancellation, data export/deletion and customer communications.
8. **Operational acceptance:** execute on-prem installation, monitoring, backup/restore, migration/rollback and incident drills on a representative host. CI smoke tests are not customer-host acceptance.
9. **Finance reconciliation:** reconcile contracts, usage, invoices, refunds, provider settlements and bank receipts. Do not equate invoiced amounts with cash received or recognised revenue.
10. **Signed release decision:** legal/compliance, finance, security and operations owners approve a versioned release scope and explicitly list excluded capabilities.

## 4. Restricted launch posture until blockers are signed

- Keep catalogue prices unpublished unless separately approved.
- Keep live payment collection disabled; sandbox-only provider mode.
- Do not represent sandbox webhook receipt as payment settlement.
- Do not activate paid data feeds without documented commercial data rights.
- Do not distribute AIR QOC or security-specific recommendations as a paid/public research service before Gate 17E and written legal clearance.
- Keep personalised investment advisory disabled.
- Preserve explicit customer approval for any permitted order ticket; no unattended strategy-triggered order placement.
- Do not provision live AWS resources or migrate customers without explicit approval.
- Keep owner-only internal analysis separate from customer-facing research and export/publication.
- Keep margin, CAC, LTV, channel attribution and historical retention unreported where source data is absent.

## 5. Acceptance and sign-off record

This record is not a substitute for signatures. The release cannot be marked READY until every required owner provides evidence and signs the exact release candidate.

| Sign-off | Required artifact | Status |
|---|---|---|
| Legal counsel | Entity/jurisdiction/product applicability opinion | BLOCKED — not supplied |
| Compliance owner | Gate 17E control evidence and release authorization | BLOCKED — not signed |
| Finance owner | Tax, invoice, refund, settlement and revenue-recognition approval | BLOCKED — not signed |
| Data-rights owner | Exchange/vendor commercial rights matrix | BLOCKED — not supplied |
| Security owner | Security review, privacy and incident-response approval | BLOCKED — not signed |
| Operations owner | Support/SLA, backup/restore, monitoring and rollback acceptance | BLOCKED — not signed |
| Product owner | Exact product/plan/features, prices and exclusions | PENDING formal approval |

## 6. Exit criteria

Gate 17F-10 may be marked **CI PASSED** only after its automated acceptance checks pass. It may be marked **ENVIRONMENT ACCEPTED** only after representative deployment and operational drills. It may be marked **RELEASE READY** only after every mandatory sign-off above is attached to the exact release candidate.

No automated check may fabricate or infer legal, tax, licensing, provider or owner approvals.

## 7. Immediate execution sequence

1. Maintain the restricted/no-live-payment posture.
2. Build a controlled evidence register linking each blocker to an owner, document, review date and expiry/revalidation date.
3. Add automated release guardrails that fail closed when live payment, paid data distribution or regulated research activation is requested without explicit approved configuration.
4. Run backend, PostgreSQL/RLS, Compose/Swarm and release-package acceptance.
5. Reassess Gate 17E, Gate 17B/17D and installation readiness dependencies before any release certification.
6. Publish a versioned go/no-go decision; keep the gate BLOCKED if any external sign-off or environment evidence is missing.

