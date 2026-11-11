# AIR local startup — one command

AIR local development uses Docker Compose v2 so the same services and configuration run on Windows, macOS and Linux. The local stack is separate from the production Docker Swarm deployment.

## First-time requirements

- Docker Desktop with the Linux container engine on Windows or macOS, or Docker Engine with the Compose v2 plugin on Linux.
- At least 8 GB RAM recommended; 16 GB or more is preferred for the Flutter web build and historical-data import.
- At least 15 GB free disk space recommended for images, build cache and the initial NSE CM/FO data import.
- Internet access for image builds and NSE archive downloads.

No host Python, Node.js, PostgreSQL or Redis installation is required for the local Compose startup. API dependencies run in the backend container and the PWA is built in a Flutter container.

## First launch

From the repository root:

**Windows PowerShell**
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\AIRSTART.ps1
```

**macOS / Linux**
```bash
bash ./AIRSTART.sh
```

The launcher checks Docker and Compose, runs `deploy/init-local-secrets.py` to create all eight required secrets without replacing existing values, creates the local environment file, builds the API and Flutter PWA, starts both services, waits for the API health endpoint, and opens the app.

After the first launch, the launcher installs the `AIRSTART` command in the PowerShell profile on Windows or the shell profile on macOS/Linux. Open a new terminal and run:

```text
AIRSTART
```

Run it from the AIR repository directory. It is safe to run repeatedly; Compose reuses the persistent data volume and existing secrets.

## Local URLs

- AIR app: http://localhost:8080
- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs

## Safety defaults

- Broker order execution is not enabled by this local launcher. Do not add live-order permissions while validating.
- QOC and Telegram schedulers remain disabled until their provider credentials, entitlements and destinations are explicitly configured and tested.
- NSE historical-data bootstrap is enabled and runs in the background; it can take time and requires network access.
- Local secrets are generated into `.air-secrets/`; they must never be committed or shared. Back up the credential encryption key securely if you enter real broker credentials.
- PostgreSQL persists in `postgres_data`; remaining SQLite domain stores persist in `air_data`. Customer and Admin authentication are migrated to PostgreSQL during API startup. Broker credentials, customer broker-account settings, execution policy and order ledger remain SQLite until the explicit domain-store cutover is run.
- This local stack does not create public DNS/TLS, deploy to Swarm, configure production secrets, or validate live broker trading.

## Operations

```bash
docker compose -f compose.local.yml ps
docker compose -f compose.local.yml logs -f air-api
docker compose -f compose.local.yml logs -f air-pwa
docker compose -f compose.local.yml down
```

Do not use `down -v` unless you intentionally want to delete the local AIR database and imported data.

## Troubleshooting recommendations

1. If Docker is unavailable, start Docker Desktop and ensure it is using Linux containers.
2. If a port is already in use, stop the conflicting local service or change the published ports in `compose.local.yml`.
3. If a build fails, inspect `docker compose -f compose.local.yml logs --tail 200` and the failing build output; do not treat a partially started stack as ready.
4. If API health fails, inspect the backend logs before opening the app.
5. If NSE bootstrap reports partial coverage, use the in-app retry action after checking connectivity and available disk space.
6. For real broker data, configure each account in AIR Admin and verify both historical and live channels. A connected account is not proof of tick delivery.
