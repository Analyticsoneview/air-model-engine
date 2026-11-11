# Self-hosted Docker Swarm deployment (single-node lab)

This stack serves the Flutter PWA and API on a private overlay network. It is a **single-replica lab deployment**, not a highly available production cluster. Authentication, account, credential and order stores currently use SQLite; OAuth state is process-local. Do not scale the API above one replica until shared database and OAuth-state services are implemented.

## 1. Build images

From the repository root:

```bash
docker build -t air-model-engine-api:lab ./backend
docker build --build-arg AIR_API_BASE_URL=https://api.example.com -f deploy/pwa.Dockerfile -t air-model-engine-pwa:lab .
```

The PWA build embeds the API base URL at compile time. Use the public HTTPS API URL, not localhost. For multi-node Swarm, push both images to a private registry and set `AIR_BACKEND_IMAGE` and `AIR_PWA_IMAGE` to immutable image references.

## 2. Create Docker secrets

Generate keys on the server. Keep them outside source control and do not paste them into chat.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | docker secret create air_jwt_secret -
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | docker secret create air_credential_key -
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | docker secret create air_admin_api_key -
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | docker secret create air_admin_mfa_key -
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

The helper records the operator's E.164 mobile number in AIR_OPERATOR_CUSTOMER_IDS. The operator must submit an access request from the AIR app. Approve the first device with the root-only admin key using deploy/air-admin-cli.sh. After the operator device is approved, use the in-app Admin tab to manage later customer requests.

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
- SQLite and in-memory OAuth state require one API replica. PostgreSQL, Redis-backed OAuth state, migrations, shared audit storage and HA deployment are not implemented yet.
- Configure a TLS reverse proxy, strict firewall rules, monitoring, log retention and backup rotation.
- Broker API plans, market-data entitlements, static IP approvals, instrument masters and exchange data redistribution rights must be verified separately.
- No live order permission is enabled by this deployment. Live trading must remain disabled until provider-specific preflight, reconciliation and explicit confirmation tests pass.


## 9. Customer mobile access and administrator approval

Customers enter a mobile number in international E.164 format (for example `+14155550123`). No OTP, WhatsApp, SMS, email or password is used. The first request is tied to the app's device identifier and remains `PENDING` until approved.

Use the administrator API key stored in the `air_admin_api_key` Docker secret:

```bash
curl -H "X-AIR-ADMIN-KEY: $AIR_ADMIN_API_KEY" \
  "https://api.example.com/api/v1/admin/access-requests?status=PENDING"

curl -X PUT -H "X-AIR-ADMIN-KEY: $AIR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status":"APPROVED","note":"Approved by AIR admin"}' \
  "https://api.example.com/api/v1/admin/access-requests/<request_id>"
```

Set `status` to `REJECTED` or `BLOCKED` to deny access. Blocking or rejecting invalidates existing device sessions immediately. The mobile app securely stores its approved session and restores it on subsequent launches. Each new device requires its own approval.

The mobile number is an identifier, not proof of ownership. Since customer identity verification is intentionally omitted, the administrator must make the access decision using the request details and any separate business process.


## GitHub Actions deployment

For automated image builds and gated SSH deployment from GitHub Actions, follow [GITHUB_DEPLOYMENT.md](./GITHUB_DEPLOYMENT.md). Production deployment is manual and restricted to workflow dispatch from `main`.


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

