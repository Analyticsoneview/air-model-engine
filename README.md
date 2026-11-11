# AIR Model Engine

**Analytical Investment Research (AIR)**

> Find the opportunity. Validate the evidence. Manage the risk.

AIR is a self-hosted research and broker-connectivity foundation with a Flutter mobile/web client and FastAPI backend. The project is being developed in guarded stages; it is not yet a production trading system.

## Repository layout

- `mobile/` — Flutter client for Android and iPhone/PWA.
- `backend/` — FastAPI authentication, customer-owned broker accounts, encrypted credential vault, market-data routing and execution safety foundations.
- `deploy/` — Docker Swarm deployment guide, self-hosted PWA Dockerfile and Nginx SPA configuration.
- `docker-stack.yml` — single-replica lab stack for API and PWA.
- `.github/workflows/` — backend tests and Flutter build/test workflows.

## Current verified scope

- Backend unit tests passed in earlier GitHub Actions runs. The latest PR checks currently fail before a runner starts (no steps/logs), so the newest commits remain unverified.
- Earlier recorded runs produced an Android lab APK and unsigned iOS lab IPA. The latest Android workflow retry is currently blocked before runner startup; the new signed customer APK workflow has not yet run. The iOS IPA is not installable without Apple signing; use the PWA route for iPhone without an Apple Developer membership.
- Flutter web analysis, tests and self-hosted PWA bundle workflow are being validated separately.
- Broker REST foundations exist for Angel One, DhanHQ, Zerodha, Upstox and FYERS. Dhan has the furthest market-feed integration; real-account entitlements and streaming for all brokers are not yet validated.
- AIR QOC now has a read-only Dhan option-chain path, expiry lookup, normalized private SQLite snapshot storage and a Flutter research screen. An optional 15:45 IST weekday snapshot scheduler is implemented but disabled by default; it requires a registered Dhan account, encrypted credentials and verified Data API entitlement. It discovers the NSE F&O universe from Dhan's instrument master (with a configured fallback list), captures active-expiry option chains, then automatically runs the evidence-first EXPIRYSCAN liquidity screen. The Model Engine app refreshes the scan every five minutes while signed in. EXPIRYSCAN is not a qualified AIR QOC signal.
- Broker order permission is intentionally disabled. Do not use this project for live order placement.

## Run backend tests

```bash
cd backend
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest -q
```


## Separate administrator authentication

The app includes a dedicated **More → Administrator Sign In** console. It is independent of customer mobile approval and uses administrator email, password and TOTP MFA with a separate 20-minute, server-revocable JWT session. Super Admin manages administrator accounts and audit events; Admin reviews customer access; Research Admin is read-only. The first Super Admin is created once with `cd backend && python -m scripts.bootstrap_admin` (or from the deployed API container). Configure `AIR_ADMIN_MFA_KEY_FILE` with a persistent Fernet key and `AIR_JWT_SECRET` before bootstrap. The Swarm stack provisions the MFA key as the `air_admin_mfa_key` Docker secret. Never store bootstrap passwords, TOTP provisioning URIs or key material in source control.

## Self-hosted deployment

Follow [Docker Swarm deployment](deploy/DOCKER_SWARM.md). It covers Docker secrets, first-operator provisioning, PWA/API routing and the current single-replica limits.

For the end-to-end Ubuntu installer, Caddy HTTPS setup, self-hosted GitHub runner and first operator activation, follow [AIR Installation](deploy/INSTALLATION.md). For the signed Android customer APK, follow [Android Release](deploy/ANDROID_RELEASE.md).

## AIR MASTER lifecycle layer

- `GET /api/v1/model-engine/master` exposes a canonical, customer-scoped MASTER aggregation over persisted verified ledger rows.
- The mobile Model Engine uses the shared AIR mobile approval session; it no longer presents a second email/password sign-in form.
- MASTER views include OPEN (NEW + HOLD), NEW, HOLD, REENTRY, SLHIT, TARGETS, EXPIRED, SURVIVOR, WAIT, EXPIRYSCAN and COMBINED, with summary counts and audit checks.
- SURVIVOR is a cross-cutting watchlist for contracts with 0–7 calendar days to expiry. It does not overwrite the original lifecycle status.
- WAIT remains empty unless an upstream workflow explicitly persists pending candidates. EXPIRY78, ORIGINAL366 and RECOVERY are named in the canonical command vocabulary but remain deferred until their precise source/eligibility rules are implemented. Pinned emoji/icon mapping is also intentionally not guessed.
- This aggregation is not the full AIR QOC signal-generation engine and does not create orders. It only organizes persisted verified signals.

## Important limitations

- PostgreSQL 16 and Redis 7 infrastructure, persistent volumes, Docker secrets and API connectivity health checks are provisioned. Existing domain repositories (including Admin/customer auth, accounts, credentials, QOC and instrument masters) are still SQLite-backed during staged migration. Redis is not yet authoritative for sessions, rate limits or OAuth state. Keep one API replica until those migrations and concurrency tests pass.
- Live broker credentials, market-data permissions, provider streaming and execution have not been validated against the user's broker accounts.
- Full AIR QOC scoring/qualification, multi-session underlying/option confirmation, validated backtests and intraday live monitoring are not yet complete. EXPIRYSCAN's EOD liquidity screen is automated after each successful capture, but it does not generate trade entries, SLs, targets or QOC scores. Optional Dhan token renewal is limited to active tokens originally generated from Dhan Web and remains disabled unless explicitly configured. Dhan option-chain snapshots alone are not a qualified signal.
- Configure TLS, firewalling, backups, monitoring and restore testing before any internet-facing deployment.

Never treat a placeholder, sample response or unverified broker connection as a live market signal.


## One-command cross-platform local startup

Use Docker Compose v2 for the same local AIR stack on Windows, macOS and Linux. Follow [Local Setup](LOCAL_SETUP.md), including the trusted-LAN Android connection and firewall guidance. After the one-time bootstrap, open a terminal in the repository and run the single command `AIRSTART`. The launcher invokes the shared secret bootstrap to create and validate all eight required local secrets without replacing existing values, builds the backend and Flutter PWA, starts services, waits for API health and opens the local app. Local trading execution remains disabled; QOC and Telegram schedulers remain off until deliberately configured.
