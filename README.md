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

- Backend unit tests have passed in GitHub Actions on recent commits.
- Android lab APK and unsigned iOS lab IPA builds passed on the recorded workflow run. The iOS IPA is not installable without Apple signing; use the PWA route for iPhone without an Apple Developer membership.
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

## Self-hosted deployment

Follow [Docker Swarm deployment](deploy/DOCKER_SWARM.md). It covers Docker secrets, first-operator provisioning, PWA/API routing and the current single-replica limits.

## Important limitations

- SQLite and process-local OAuth state mean one API replica only. PostgreSQL, Redis-backed OAuth state, migrations and HA are not implemented.
- Live broker credentials, market-data permissions, provider streaming and execution have not been validated against the user's broker accounts.
- Full AIR QOC scoring/qualification, multi-session underlying/option confirmation, validated backtests and intraday live monitoring are not yet complete. EXPIRYSCAN's EOD liquidity screen is automated after each successful capture, but it does not generate trade entries, SLs, targets or QOC scores. Optional Dhan token renewal is limited to active tokens originally generated from Dhan Web and remains disabled unless explicitly configured. Dhan option-chain snapshots alone are not a qualified signal.
- Configure TLS, firewalling, backups, monitoring and restore testing before any internet-facing deployment.

Never treat a placeholder, sample response or unverified broker connection as a live market signal.
