# AIR Internal Personal-Analysis Workspace

## Purpose

AIR provides a private technical-analysis workspace for the product owner's own research and decisions. This is a product access boundary, not a legal opinion or an exemption from securities, broker, exchange, data-provider, privacy or other applicable rules.

## Owner authentication

The API uses the separate administrator authentication system (password + TOTP MFA). Configure:

- `AIR_INTERNAL_OWNER_EMAIL`: exact email address of the one administrator permitted to access the internal workspace policy API.
- The configured identity must also have the `SUPER_ADMIN` role.
- If the variable is absent, the API fails closed with HTTP 503.
- Any other administrator, including another Super Admin, receives HTTP 403.

Keep this value in the deployment's secret/configuration management process; do not commit a real owner email or credentials to source control. The owner identity must match the email used by the first/bootstrap administrator unless deliberately changed by the deployment operator.

## Current API slice

- `GET /api/v1/internal-workspace/policy` returns the effective owner-only policy.
- The response labels content `INTERNAL — NOT FOR DISTRIBUTION`.
- Customer sharing and publication are disabled.
- Personalised investment advice, automated order execution and broker order submission are disabled.
- `GET/POST /watchlists`, `PUT/DELETE /watchlists/{item_id}`: owner-scoped private watchlists.
- `GET/POST /notes`, `PUT/DELETE /notes/{item_id}`: owner-scoped private research notes.
- `GET /audit`: owner-scoped create/update/delete audit events.
- Every stored row is keyed by the authenticated administrator ID as well as item ID. A second owner cannot list, read, update or delete another owner's items.
- SQLite persistence defaults to `data/internal_workspace.sqlite3`; configure `AIR_INTERNAL_WORKSPACE_DB_PATH` to a persistent mounted-volume path in deployment. Back up this database with the other application state.
- Watchlist symbols are normalized to uppercase and deduplicated. Notes and watchlists receive the internal classification label on API reads.
- No public/customer sharing, publication or export endpoint is provided. Export auditing and analysis-endpoint integration remain subsequent work.

## Regulatory boundary

- Use only for the owner's own analysis and decisions.
- Do not distribute security-specific recommendations, QOC calls, strike/entry/stop-loss/target outputs or reports to customers, public channels or paid groups until written legal classification and any required registration and controls are in place.
- Technical-analysis methodology alone does not exempt security-specific recommendations from the Research Analyst Regulations.
- Do not infer that manual approval automatically exempts a broker/API workflow from retail algo requirements.
- Maintain separate assessments for data licences, broker terms, insider-trading, market manipulation, privacy, tax and cross-border activity.

## Acceptance criteria for this slice

1. Unauthenticated callers are rejected by administrator authentication.
2. A non-owner Super Admin is rejected.
3. An ADMIN or RESEARCH_ADMIN is rejected even if their email matches the configured owner.
4. Missing owner configuration fails closed.
5. Only the configured Super Admin receives the restrictive internal policy.

## Private persistence API

Example watchlist creation:

```http
POST /api/v1/internal-workspace/watchlists
Authorization: Bearer <administrator-token>
Content-Type: application/json

{"name":"Index watch","symbols":["NIFTY","BANKNIFTY"]}
```

Example private note creation:

```http
POST /api/v1/internal-workspace/notes
Authorization: Bearer <administrator-token>
Content-Type: application/json

{"title":"Session study","content":"Wait for price/volume confirmation.","tags":["ORB"],"related_symbols":["NIFTY"]}
```

The API deliberately does not expose a public URL, customer tenant route, share action or automated order action. Deployments must mount the configured database path on persistent storage and include it in backup/restore drills.
