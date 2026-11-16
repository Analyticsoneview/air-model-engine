# AIR installation and initial data readiness

## Purpose

AIRSTART is a one-click local installation entry point. Container liveness is not the same as full AIR readiness. The installer starts the application services, then waits for the initial NSE data and research bootstrap before opening the PWA.

## Deployment Manager and release lifecycle

The cross-platform `AIRDEPLOY` wrapper invokes `scripts/air_manager.py`. Its validate/doctor/install/upgrade/status/diagnose/package actions are shared by Windows PowerShell and Linux/macOS Bash wrappers. The `onprem-single` profile is self-hosted and does not require AWS. AWS profiles can be validated and packaged without AWS credentials; live cloud provisioning remains deferred until an approved AWS environment is available.

The manager routes install and upgrade through the platform's `AIRSTART` implementation. Upgrade validates the Compose model, refreshes the PostgreSQL/Redis/RabbitMQ base images, rebuilds FastAPI/workflow-worker/PWA images and then uses the same full `/ready` acceptance gate as first install. Existing named volumes and non-empty secrets are preserved. Backups must be verified before upgrading because startup migrations are not automatically rolled back.

The release builder creates a versioned source bundle with a service inventory, release manifest and SHA-256 checksums. CI combines it with a separately checksummed OCI image archive containing the tested FastAPI/worker and PWA images plus PostgreSQL, Redis, RabbitMQ and Caddy. The source bundle includes migrations, Flutter PWA source, configuration, workflow worker/scheduler, installers and deployment profiles. It excludes local secrets, environment files, databases, runtime data and signing keys.

## Mandatory first-install data

- NSE CM UDiFF daily bhavcopy: minimum 12 calendar months.
- NSE FO UDiFF daily bhavcopy: minimum 12 calendar months.
- Official NSE CM and FO trading-holiday calendars for every year in the selected window.
- Current official Nifty 100 constituents: exactly 100 unique symbols.
- Current official Nifty Midcap 150 constituents: exactly 150 unique symbols.
- Current official Nifty Smallcap 250 constituents: exactly 250 unique symbols.
- Combined current universe: exactly 500 unique symbols.
- Per-symbol CM EOD history coverage report.
- Existing AIR post-import strategy/research replay.
- AIR MPDSM monthly universe scan and persisted stock/options EOD snapshots.

The initial history window is configured with `AIR_NSE_HISTORY_MONTHS`. The value is clamped to 12–60 months; values below 12 cannot reduce the mandatory minimum.

## Download and recovery behaviour

- Raw NSE ZIP archives are retained under the configured AIR data volume.
- Expired FO contract rows inside the configured 12–60 month research-retention window remain queryable; only expired FO rows older than the retention cutoff are eligible for cleanup after strategy replay.
- Each market/date archive has a persisted import status, attempt counter, source URL, byte size and SHA-256 checksum.
- Existing reconciled archives are skipped on restart; only missing, failed or mismatched sessions are downloaded again.
- Bootstrap runs have durable run IDs, status history, last-processed date and checkpoint timestamps in the NSE SQLite store.
- A renewable SQLite lease enforces one bootstrap writer across processes sharing the AIR data volume. Startup, scheduled and operator-triggered runs wait for the lease instead of duplicating downloads.
- Graceful shutdown records `INTERRUPTED`; an abrupt process loss is recovered after the 180-second lease expires. The startup coordinator retries lease acquisition for up to four minutes.
- A previously READY bootstrap for the same end date and history window is a no-op on ordinary startup. A new EOD date or incomplete checkpoint starts a resumable run.
- Failed or incomplete sessions are reconciled and repaired as a paired CM/FO session.
- Missing expected archives and failed downloads prevent full readiness.
- The current trading date is excluded before 21:00 Asia/Kolkata so an unpublished EOD archive is not misclassified as missing.
- Dated index constituent snapshots are retained. A failed refresh never invalidates a previously validated exact-count snapshot; the last attempt status/error remains visible. A first-ever download without a valid snapshot remains incomplete.

The status endpoint exposes recent `bootstrap_runs`, the active lease state and per-archive attempt/checksum metadata. The `/ready` response includes the current run ID, resume origin, last processed date, last checkpoint, expected/imported counts and failed/missing archive counts. This is diagnostic evidence; CI does not claim that a customer host has downloaded live NSE data.

## Per-symbol coverage policy

The current union of the three index lists must contain 500 unique symbols. Each symbol is checked against imported CM EOD records over the initial history window.

- `READY`: every symbol has at least 45 sessions.
- `READY_WITH_WARNINGS`: every symbol has at least one session, but one or more have fewer than 45 sessions. These are flagged as insufficient; downstream scanners must exclude them from calculations requiring 45 observations.
- `BLOCKED`: one or more current index constituents have no CM EOD observations.

The report includes each symbol's session count, coverage percentage, first date, last date and coverage status.

## Health versus readiness

- `GET /health` is a liveness/dependency check. It must remain usable while historical data downloads are running.
- `GET /ready` is the full installation gate. It returns HTTP 200 only after infrastructure dependencies, complete CM/FO archive coverage, all three index snapshots, per-symbol coverage, the existing AIR post-import research replay, and a fresh workflow-runtime heartbeat proving RabbitMQ connectivity and live scheduler/publisher/executor/monitor threads.
- The installer must not use `/health` as proof of full application readiness.

## Installer behaviour

Windows: `AIRSTART.ps1`

Linux: `AIRSTART.sh`

Both scripts:
1. Validate Docker and Compose.
2. Generate or reuse local secrets.
3. Build and start PostgreSQL, Redis, RabbitMQ, FastAPI, workflow worker and PWA.
4. Verify service health.
5. Poll `/ready` before opening the PWA.
6. Wait up to 720 minutes by default. Override with `AIR_INSTALL_READINESS_TIMEOUT_MINUTES`.

## Persistent paths

The local Compose and Swarm configurations persist:
- NSE CM/FO SQLite data and raw archives under `/var/lib/air`.
- NSE index-universe dated snapshots at `/var/lib/air/nse_universe.sqlite3`.

The application remains research-only; this readiness process does not enable broker order placement.

## Acceptance boundary

Passing unit/CI tests validates code and deterministic checks. It does not prove that a customer installation has downloaded NSE archives or that external NSE endpoints were reachable. A first-install acceptance run must record actual start/end dates, expected/imported archive counts, missing/failed archives, index counts, per-symbol coverage, strategy replay result and final readiness response.
