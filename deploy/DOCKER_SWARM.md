# Self-hosted Docker Swarm deployment (single-node lab)

This stack serves the Flutter PWA and API on a private overlay network. It is a **single-replica lab deployment**, not a highly available production cluster. PostgreSQL 16, Redis 7 and RabbitMQ 4 are provisioned with persistent volumes and Docker secrets. The separate workflow worker consumes RabbitMQ events and schedules durable time-trigger events; it does not place broker orders. The API container applies Alembic migrations before starting Uvicorn. Broker account ownership, market-data entitlements/selections and encrypted broker credentials use PostgreSQL through the shared `air_database_url` secret. Authentication, sessions, QOC, instruments and remaining repositories are still on their existing stores until their own migrations and tests are complete. Do not scale the API above one replica until repository migration and shared-state tests are complete.

## 1. Build images

From the repository root:

```bash
docker build -t air-model-engine-api:lab ./backend
docker build --build-arg AIR_API_BASE_URL=https://api.example.com -f deploy/pwa.Dockerfile -t air-model-engine-pwa:lab .
```

The PWA build embeds the API base URL at compile time. Use the public HTTPS API URL, not localhost. For multi-node Swarm, push both images to a private registry and set `AIR_BACKEND_IMAGE` and `AIR_PWA_IMAGE` to immutable image references.

## 2. Create Docker secrets

The installer provisions persistent PostgreSQL/Redis/RabbitMQ passwords and connection-URL secrets automatically. If deploying manually, create the additional secrets below (use the same password values in the URL secrets):

```bash
openssl rand -hex 32 | docker secret create air_postgres_password -
openssl rand -hex 32 | docker secret create air_redis_password -
openssl rand -hex 32 | docker secret create air_rabbitmq_password -
# Create air_database_url containing postgresql+psycopg://air:<password>@postgres:5432/air
# Create air_redis_url containing redis://:<password>@redis:6379/0
```

Generate keys on the server. Keep them outside source control and do not paste them into chat.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | docker secret create air_jwt_secret -
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | docker secret create air_credential_key -
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | docker secret create air_admin_api_key -
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" | docker secret create air_admin_mfa_key -
```

Back up the Fernet key securely. Losing it makes encrypted broker credentials unrecoverable. The API reads all three secrets from Docker's `*_FILE` paths. Keep the admin key private; it is used to review customer requests and run operator-only backend actions.

## 3. Bootstrap the first Super Admin

The administrator console uses a separate email/password/TOTP identity. Create the first administrator once, from the API container, after the stack is running:

```bash
docker exec -it "$(docker ps --filter name=air_air-api -q | head -n1)" sh
cd /app
python -m scripts.bootstrap_admin
```

The container must include the bootstrap script and receive `AIR_ADMIN_MFA_KEY_FILE=/run/secrets/air_admin_mfa_key`. Enter a unique email and a strong password (12+ characters), then scan the one-time TOTP provisioning URI with an authenticator app. Keep the URI private; it is displayed only during bootstrap. The bootstrap refuses to create a second initial Super Admin. Do not put passwords, TOTP URIs, or key material in chat, shell history, or source control.

Open AIR → More → Administrator Sign In. Enter the administrator email, password and current six-digit authenticator code. The separate Admin session is stored in platform secure storage and expires after 20 minutes. Use the key icon to rotate the password and the sign-out action to revoke the server-side session. Super Admin can create/deactivate administrators, change roles, review audit events and manage pending customer access requests. Research Admin is read-only for customer access review and cannot manage administrator accounts.

## 3. Bootstrap the first operator

The mobile number is the stable operator identity. Run the helper after creating /etc/air/air.env:

```bash
cd /opt/air-model-engine
sudo python3 backend/scripts/bootstrap_operator.py
```

The helper records the operator's E.164 mobile number in AIR_OPERATOR_CUSTOMER_IDS. The operator must submit an access request from the AIR app. A Super Admin must sign in through the dedicated Administrator Sign In flow, open the Admin Console, review the pending request and approve or reject it using a fresh six-digit authenticator code. The operator-side access-request view is read-only; do not use the legacy admin-key CLI to mutate customer access.

Mobile numbers are identifiers only. This no-OTP design does not prove phone ownership; approval must be based on a separate trusted process. Do not enable public signup.

## 4. Set deployment variables

```bash
export AIR_OPERATOR_CUSTOMER_IDS="<operator-mobile-e164>"
export AIR_API_PORT=8000
export AIR_BACKEND_IMAGE=air-model-engine-api:lab
export AIR_PWA_IMAGE=air-model-engine-pwa:lab
export AIR_CORS_ORIGINS="https://air.example.com"

# Scheduled Dhan capture + automatic post-capture EXPIRYSCAN (OFF until credentials/entitlement verified)
export AIR_QOC_SCHEDULER_ENABLED=false
export AIR_QOC_DHAN_AUTO_RENEW_ENABLED=false
export AIR_QOC_DHAN_ACCOUNT_ID="<registered-dhan-account-id>"
export AIR_EXPIRYSCAN_MAX_DTE=45
export AIR_EXPIRYSCAN_MAX_ROWS=2000
# Optional fallback universe only if official Dhan instrument-master discovery is unavailable.
# Use verified IDs/segments only; never guess IDs.
export AIR_QOC_DHAN_UNDERLYINGS='[]'
```

For Angel One, configure actual server client local IP, public IP and MAC address. Do not use placeholder values.

## 5. Deploy

```bash
docker stack deploy -c docker-stack.yml air
docker service ls
docker service logs -f air_air-api
docker service logs -f air_air-pwa
docker service logs -f air_air-workflow-worker
docker service logs -f air_rabbitmq
```

The PWA listens on port 8080 inside the overlay as `air-pwa`; the API listens on port 8000 as `air-api`. Configure your existing TLS reverse proxy to route the app hostname to `air-pwa:8080` and API hostname to `air-api:8000`. Do not expose the PWA container directly to the public internet without TLS. The API is not published on the host; only the Caddy HTTPS ingress exposes ports 80 and 443.

## 6. AIR QOC data capture

The AIR QOC Dhan data routes are read-only. The mobile AIR QOC tab can check Dhan Data API entitlement, retrieve active expiries, fetch a live option chain and store normalized CE/PE observations in the private SQLite research database. A single snapshot is not an AIR QOC qualification signal.

The weekday EOD capture scheduler runs at 15:45 Asia/Kolkata only when explicitly enabled. Configure the registered Dhan account and encrypted credentials first. The scheduler discovers validated NSE F&O underlyings from Dhan's detailed instrument master; the JSON universe below is only a fallback if master discovery is unavailable. It fetches each discovered underlying's active expiries sequentially and waits at least 3.1 seconds between option-chain requests to respect Dhan's option-chain rate limit. For the full F&O universe, the run can take substantial time and may span a long period. After capture, the backend automatically runs EXPIRYSCAN on the newly stored observations and reports contract and 0–7 DTE SURVIVOR counts. The app refreshes the ledger and scan every five minutes while signed in.

```bash
# Enable only after Data API entitlement and permitted use are confirmed.
export AIR_QOC_SCHEDULER_ENABLED=true
export AIR_QOC_DHAN_ACCOUNT_ID="<registered-dhan-account-id>"
export AIR_QOC_DHAN_UNDERLYINGS='[{"security_id":13,"segment":"IDX_I","label":"NIFTY"}]'
```

Manual operator-only run:

```text
POST /api/v1/air-qoc/run-eod-capture
```

Optional token renewal is available only for an active access token originally generated from Dhan Web. Enable it separately with `AIR_QOC_DHAN_AUTO_RENEW_ENABLED=true`; Dhan's RenewToken endpoint invalidates the current token and returns a new 24-hour token. API-key/OAuth tokens and expired tokens must use their respective Dhan authorization flow. Keep this switch off until the account's token origin is confirmed. The new token is written back to AIR's encrypted credential vault. No raw NSE bhavcopy downloader is enabled; written NSE permission remains a prerequisite for automated NSE website collection. The scheduler captures normalized snapshots and runs the EXPIRYSCAN liquidity screen. EXPIRYSCAN reports observed volume, OI, bid/ask spread and DTE; it does not assign AIR QOC scores, entry, SL or targets because a single EOD snapshot cannot establish underlying candle confirmation, intraday premium acceleration or session volume/OI progression. No orders are placed.
## 7. Mobile build workflow

The GitHub Actions workflow `.github/workflows/ios-pwa.yml` runs Flutter analysis and tests, builds the web app, and uploads `air-pwa-web` as a downloadable artifact. Set repository variable `AIR_API_BASE_URL` to the deployed HTTPS API URL. This avoids GitHub Pages permissions and keeps hosting self-managed.

## 8. Provisioning and production blockers

- Customer signup is disabled by default. Provision the initial operator through the backend's trusted administrative bootstrap procedure; do not enable public signup on an exposed instance.
- Back up the `air_data` volume and test restore before storing broker credentials.
- The API image includes `alembic.ini` and the migration scripts. Its startup command runs `python -m alembic upgrade head` and starts Uvicorn only if migration succeeds. Both Compose and Swarm set `AIR_ACCOUNT_DATABASE_URL_FILE` and `AIR_CREDENTIAL_DATABASE_URL_FILE` to `/run/secrets/air_database_url`; the credential encryption key remains `/run/secrets/air_credential_key`. Migration failure prevents API startup rather than serving against a partial schema.
- Broker account ownership, market-data entitlements/selections and encrypted credentials are PostgreSQL-backed after this gate. Authentication, sessions, QOC, instrument masters and remaining repositories are not yet fully migrated. Redis is not yet the authoritative session/rate-limit store. Keep the API at one replica.
- Configure a TLS reverse proxy, strict firewall rules, monitoring, log retention and backup rotation.
- Broker API plans, market-data entitlements, static IP approvals, instrument masters and exchange data redistribution rights must be verified separately.
- No live order permission is enabled by this deployment. Live trading must remain disabled until provider-specific preflight, reconciliation and explicit confirmation tests pass.


## 9. Customer mobile access and administrator approval

Customers enter a mobile number in international E.164 format (for example `+14155550123`). The first request is tied to the app's device identifier and remains `PENDING`; pending customers receive no dashboard or broker access.

A Super Admin or authorized Research Admin reviews requests in the dedicated AIR Admin Console:

1. Review the customer mobile number, request date, device details and current status.
2. Choose Approve or Reject.
3. Enter a fresh six-digit code from the administrator's authenticator app for that decision.
4. The backend verifies the administrator's active account and role, TOTP freshness and one-time use before applying the decision.
5. The decision history records the request, customer, administrator, role, decision and timestamp. A reused or stale code must be rejected.

Do not use the legacy operator access-request view or the `deploy/air-admin-cli.sh` mutation commands to approve, reject or block customers. The operator view is read-only; customer access decisions must go through the TOTP-protected Admin Console.

Administrator approval does not verify ownership of the customer's mobile number and does not assign a subscription. Phone ownership verification by SMS is a separate capability and is not implemented until an SMS provider and credentials are configured. Do not enable public signup or represent a pending request as verified.

## 10. Account-wise P&L email reports

AIR supports multiple assigned accounts for the same broker. Each account is fetched
and reported independently; reports are never merged across account IDs. The Model
Engine P&L Calendar includes **Broker Account P&L Email Reports**:

1. Enter a destination email and request a verification code.
2. Confirm the six-digit code sent to that mailbox.
3. AIR then schedules a separate daily report for each assigned broker account at
   **16:00 Asia/Kolkata (weekdays)**. The report includes a PDF summary and a CSV
   containing broker-returned position, order and holding records.
4. Use **Generate & Email Account Reports Now** for an on-demand run. Delivery and
   per-account failures appear in report history.

The P&L summary uses fields returned by the broker's positions endpoint. If a broker
does not return a particular P&L field, AIR labels it unavailable; it does not
substitute the strategy-ledger estimate or fabricate a zero. A disconnected account,
missing credentials, failed broker request or empty statement is recorded as FAILED
for that account and does not prevent other accounts from being reported. A manual
run can retry a failed account.

Configure the SMTP host, port, username and From address as deployment environment
variables. Store the SMTP password in a Docker secret and create it before stack
deployment:

```bash
printf '%s' '<SMTP password or app password>' | docker secret create air_smtp_password -
```

Set these deployment variables in the protected server environment (do not commit
them to source control):

```bash
AIR_SMTP_HOST=smtp.your-provider.example
AIR_SMTP_PORT=587
AIR_SMTP_USERNAME=reports@your-domain.example
AIR_REPORT_FROM_EMAIL=reports@your-domain.example
```

The stack mounts the secret at `/run/secrets/air_smtp_password`. The API requires
SMTP configuration to send verification codes and reports. Without it, email setup
and delivery return an explicit failure; no report is marked sent. Email verification
codes expire after ten minutes and only their hash is stored. The recipient is
customer-scoped and must be verified before report delivery.

## 11. Workflow runtime acceptance, operations alerts and database recovery

The workflow worker monitors its own runtime and durable queue state. It reports an
operations alert for a stale or degraded worker, an unreachable RabbitMQ broker,
an outbox backlog above the configured threshold, publisher retry exhaustion, a
dispatch queue backlog, or any message in the dead-letter queue. Alerts use the
admin/platform `AIR_WORKFLOW` Telegram destination only; customer-scoped Telegram
destinations are not used for infrastructure health messages.

Configure an administrator-owned Telegram destination for the `AIR_WORKFLOW`
strategy in the Admin Telegram Destinations screen. Keep the worker's Telegram bot
token in the `air_telegram_bot_token` Docker secret. The monitor polls every
30 seconds by default; configure `AIR_WORKFLOW_ALERT_POLL_SECONDS` to change the
interval and `AIR_WORKFLOW_ALERT_BACKLOG_THRESHOLD` to change the queue/outbox
backlog threshold (default 100). Alert delivery is deduplicated per admin
destination and its delivery ledger is stored on the persistent `air_data` volume.
If no admin destination is configured, alerts are logged but are not delivered.

### PostgreSQL backup

Run this on a Swarm manager after confirming the PostgreSQL service is healthy:

```bash
sudo AIR_WORKFLOW_BACKUP_DIR=/var/backups/air/workflows \
  bash deploy/backup-workflow-postgres.sh
```

The script writes a PostgreSQL custom-format archive and SHA-256 sidecar with
owner-only permissions. It reads the database password from the mounted Docker
secret inside the PostgreSQL task; it does not print the secret. Backups remain
on the host. Copy them to encrypted off-host storage and apply a tested retention
policy; a local backup alone is not disaster recovery.

### Non-destructive restore verification

Choose a fresh database name other than `air`. The script refuses to overwrite an
existing database and never swaps the restored database into production:

```bash
sudo bash deploy/restore-workflow-postgres-verify.sh \
  /var/backups/air/workflows/air-postgres-YYYYMMDDTHHMMSSZ.dump \
  air_restore_verify
```

It verifies the archive checksum when the sidecar exists, restores into the new
database using the PostgreSQL 16 server image's matching client tools, and checks
that workflow definitions, events, outbox, runs, steps, audit, exchange calendar,
worker heartbeat tables and the workflow lease index exist. It prints row counts
and retains the restore database for operator inspection. Review the restored
data before manually removing that verification database.

### Deployment smoke checks

The Swarm deployment script now waits for PostgreSQL, Redis, RabbitMQ, API, worker
and PWA services to report one healthy replica. It then requires a fresh
`RUNNING` workflow-worker heartbeat, a live RabbitMQ connection and all worker
components reporting healthy. A process-only worker health check is not considered
sufficient.

The GitHub deployment workflow intentionally keeps production deployment behind
an explicit `workflow_dispatch` approval (`deploy=true`) and the configured
SSH secrets/known-hosts. Pull-request CI uses disposable services and does not
deploy to the production host. Do not bypass that approval gate or treat a successful
image build as a production deployment.

Workflow execution remains limited to research and alert/notification actions.
Broker order placement is not enabled by the workflow engine.
