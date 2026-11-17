# Gate 17F-10 — Signed release approval document

## Purpose

The release approval evaluator provides a fail-closed evidence gate for protected commercial capabilities. A feature is not approved by a subscription tier, deployment profile, environment boolean or administrator session alone.

Protected capabilities currently registered:
- `live_payment_collection`
- `paid_public_research`
- `paid_data_redistribution`
- `personalised_investment_advice`
- `automated_broker_order_execution`
- `live_aws_provisioning`

## Required configuration

- `AIR_RELEASE_APPROVALS_FILE`: path to the owner-controlled JSON approval document.
- `AIR_RELEASE_APPROVAL_HMAC_KEY_FILE`: path to an owner-controlled secret file containing at least 32 bytes.

If either is absent, unreadable or invalid, every protected capability is denied. No key is included in source control, images, example files or release artifacts.

## Approval document contract

The JSON document must contain:
- `schema_version: 1`
- a unique `release_id`
- `status: "APPROVED"`
- `approved_capabilities`: explicit allowlist; approval of one capability does not approve another
- `expires_at`: timezone-aware ISO-8601 expiry
- `approvals`: a signed evidence reference for each of `legal`, `compliance`, `finance`, `data_rights`, `security`, and `operations`
- `signature`: lowercase or uppercase hexadecimal HMAC-SHA256 over the canonical JSON document excluding the signature field

Canonical JSON uses sorted keys, compact separators and UTF-8 encoding. The HMAC key must be held and used only by the authorized release owner in a controlled signing process. Do not put the key in the approval document or commit it.

## Runtime behavior

- The evaluator rejects missing/unknown capabilities, absent documents, missing/short keys, invalid signatures, non-approved decisions, absent capability allowlisting, missing domain approvals/references and expired approvals.
- `GET /api/v1/commercial/release-controls/status` is administrator-authenticated and reports the approval state for every protected capability. It is read-only and does not activate a feature.
- Future endpoints, background jobs and deployment actions that activate a protected capability must call `require_release_approval(capability)` immediately before activation. Do not rely on UI visibility or subscription entitlements as a security boundary.
- The current payment adapter remains sandbox-only; this guard does not add a live payment provider or live collection path.
- Current restricted catalogue entitlements remain denied. This approval mechanism is an additional gate, not a mechanism for bypassing Gate 17E or changing product/legal scope.
- A signed document is evidence supplied by accountable owners, not proof that the referenced legal, tax, data-rights or operational conclusions are correct. The named owners remain responsible for the evidence and its validity.

## Acceptance tests

Unit tests cover missing configuration, invalid signature, tampering, capability-specific scope, mandatory evidence references, expiry and unknown capability denial. Integration of this evaluator into any future live activation path must be separately tested before that path can be enabled.
