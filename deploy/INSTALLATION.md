# AIR installation and operations


## Market-data providers

The API persists independent historical and live source selections and broker-specific
instrument token mappings on the shared AIR data volume:

- `AIR_MARKET_SOURCE_DB_PATH=/var/lib/air/market_sources.sqlite3`
- `AIR_MARKET_INSTRUMENT_DB_PATH=/var/lib/air/market_instruments.sqlite3`
- `AIR_MARKET_DATA_POLL_SECONDS=3` (minimum 2 seconds; broker REST rate limits still apply)

These paths are already configured in `docker-stack.yml`. Do not store provider API
secrets in this file or in a plain-text environment variable; enter them through the
AIR Admin broker-account credential screen so they are encrypted in the credential
vault. Dhan, Zerodha, Upstox, FYERS and Angel One have native WebSocket adapter implementations
plus normalized historical REST candles. The connector uses the official broker SDK
for each live stream; Upstox V3 is Protobuf-decoded by its SDK. Stream health exposes
stale/degraded/outage states and reconnects with provider-specific retry logic. A
configurable external vendor connector is available for vendors implementing the AIR
JSON HTTPS/WSS contract. Provider subscriptions require the broker/vendor's own
instrument token/key; map tokens under **AIR Admin → Market Data Sources** from the
official instrument master.

A profile authentication handshake does not guarantee a market-data subscription
entitlement. After enabling a provider, subscribe at least one test instrument and
confirm fresh ticks in `GET /api/v1/market-data/status` before using that feed in
production. Do not use REST polling as a substitute for tick-by-tick feed requirements
without checking the provider's rate limits and latency.

The generic external-vendor catalog item is an adapter extension point, not a
pre-integrated vendor. A vendor must be named and its API/SDK, authentication model,
instrument master, subscription limits and licensed entitlements supplied before it
can be marked ready.

## Prerequisites

- A dedicated Ubuntu 22.04 or 24.04 server or VM.
- A static public IP or stable public DNS target.
- Two DNS names pointing to the server: the AIR app hostname and API hostname.
- Inbound TCP 80/443 and UDP 443 allowed in the hosting provider firewall; SSH must remain restricted to trusted administrator IPs.
- GitHub read access to the private AIR repository.
- An E.164 operator mobile number. This is an identifier only; the agreed no-OTP flow does not verify ownership.
- A Telegram bot token and verified chat IDs are optional during first install. Telegram remains disabled until configured.

The installer creates a single-node Docker Swarm deployment. It is not a multi-node high-availability setup. SQLite and process-local OAuth state require one API replica.

## One-command Ubuntu installation

On a fresh Ubuntu server, first clone the private repository. Git prompts for your GitHub username and a fine-grained token with read-only Contents permission; do not put the token in the command or remote URL:

~~~bash
git clone --branch feat/air-telegram-alerts https://github.com/Analyticsoneview/air-model-engine.git
cd air-model-engine
sudo bash deploy/install-air-ubuntu.sh
~~~

The installer detects and updates this clean checkout. Once PR #7 is merged, use the main branch instead. If you already have a clean checkout, the installer can also clone into /opt/air-model-engine when run from a copied script outside the repository.

The installer:
1. Installs Docker Engine and initializes single-node Swarm if needed.
2. Clones the private AIR repository into /opt/air-model-engine.
3. Prompts for app/API hostnames, TLS contact email and operator mobile.
4. Creates the Docker secrets for JWT signing, credential encryption, administrator API access and Telegram.
5. Stores the administrator API key in /etc/air/admin-api-key with root-only permissions.
6. Writes /etc/air/air.env with mode 0600.
7. Builds the FastAPI and Flutter PWA images locally.
8. Deploys the API, PWA and Caddy reverse proxy.
9. Waits for all three Swarm services to converge to one replica.

The default installer branch is feat/air-telegram-alerts while its pull request is awaiting verification. After the reviewed pull request is merged and you have cloned main, run `sudo env AIR_INSTALL_REF=main bash deploy/install-air-ubuntu.sh` to install from main. Do not deploy an unreviewed branch as a production release.

## DNS and TLS

Before the installer runs, create A records for both hostnames pointing to the Ubuntu server. Allow inbound 80/tcp, 443/tcp and 443/udp in the cloud/network firewall. Caddy requests and renews public TLS certificates automatically. Verify:

~~~bash
curl -fsS https://api.example.com/health
~~~

Use the actual hostname configured during installation. Do not distribute the app until the HTTPS API health check succeeds. The API is not published on port 8000; Caddy is the only public ingress.

## First operator activation

The installer configures AIR_OPERATOR_CUSTOMER_IDS to the operator's E.164 mobile number. The operator must:

1. Install/open the AIR app and submit an access request from their device.
2. On the server, list pending requests:

~~~bash
sudo bash /opt/air-model-engine/deploy/air-admin-cli.sh list PENDING
~~~

3. Copy the exact request_id for the operator's own device and approve it:

~~~bash
sudo bash /opt/air-model-engine/deploy/air-admin-cli.sh approve REQUEST_ID
~~~

4. Reopen the AIR app and check approval status. The Admin tab becomes available to that configured operator identity.

The administrator key is never embedded in the mobile app. Keep /etc/air/admin-api-key root-only. Ordinary customers can see and manage only their own accounts; the operator-only API lists and reviews device access requests.

Because OTP/phone verification was intentionally omitted, the mobile number is not proof of identity. Use a trusted out-of-band process to verify the operator and every customer before approval. Blocking a device revokes its active sessions.

## GitHub Actions self-hosted runner

For PR #7 backend and Android verification, use the cross-platform one-command utility in the repository root. It supports Windows 10/11 x64 and common systemd-based Linux distributions (Ubuntu, Debian, Fedora, RHEL, Rocky Linux and AlmaLinux). Follow [SELF_HOSTED_RUNNER.md](SELF_HOSTED_RUNNER.md).

The utility uses GitHub CLI browser authentication, requests a short-lived runner registration token directly from GitHub, registers the PC, sets `AIR_CI_RUNNER_LABELS`, waits for the runner to become Online, then dispatches and watches the backend and Android workflows. It does not set `AIR_RUNNER_LABELS`; Linux-only Docker/PWA workflows remain on their separately configured Linux runner.

The runner is a privileged CI machine. Do not route untrusted pull requests to it. PR #7 remains unmerged until backend tests, Flutter analysis/tests and the Android ARM64 build pass on the current PR head.

## Android customer APK

Follow ANDROID_RELEASE.md to create and protect the AIR signing keystore and configure the five GitHub variable/secrets. Then run Actions → AIR Android Customer Release. Distribute only the signed APK artifact from a successful run, together with its SHA-256 checksum. Install and test it on real Android devices before customer rollout. The workflow is ARM64 only and does not publish to Google Play.

## Telegram destination management and market-data activation

The Telegram bot token remains a Docker secret. To replace it later, run `sudo bash /opt/air-model-engine/deploy/rotate-telegram-secret.sh`. The helper creates a versioned Swarm secret, updates the stack and removes the old secret after the API service converges. Never enter the bot token in the mobile app or commit it to GitHub.

After the operator's device is approved, open **AIR Admin → Telegram destinations** in the Android app. Add one or more private chats and groups/supergroups by their numeric chat IDs. Private chat IDs must be positive; group/supergroup IDs must be negative. For every destination, choose one or more routes: RECOVERED, EXPIRY78 and EXPIRYSCAN. Destinations can be edited, disabled, re-enabled or removed without rebuilding the backend or app. A destination can receive multiple strategies, and one strategy can fan out to multiple private/group destinations.

Use **TEST** on an individual destination, or the send action in the screen toolbar to test all enabled destinations. A successful test confirms that Telegram accepted the send request; it does not guarantee that future messages will be read. The bot must already have a conversation with the private user or be a member of the group, with permission to post. Add the bot to each group and send a message in a private chat first so Telegram has established the chat.

The first saved managed destination makes the database-backed routing authoritative. Before that point, the legacy AIR_TELEGRAM_CHAT_IDS environment setting remains as a compatibility fallback. The managed destination registry is stored in the persistent application data volume (AIR_TELEGRAM_CONFIG_DB_PATH defaults to data/air_telegram_config.sqlite3). Existing destination IDs are not copied automatically into the managed registry; add and test them in the Admin screen before relying on managed routing.

The scheduler remains disabled until the bot token and destinations have been tested. Then set AIR_TELEGRAM_SCHEDULER_ENABLED=true in /etc/air/air.env and redeploy the stack. Telegram routes are strategy-specific and delivery deduplication is tracked separately per destination.

AIR_QOC_SCHEDULER_ENABLED remains false until the Dhan account, Data API entitlement, access token and instrument mappings have been verified. The deployment does not enable broker order placement.

## Operations

~~~bash
cd /opt/air-model-engine
docker stack services air
docker service ls
docker service logs -f air_air-api
docker service logs -f air_air-pwa
docker service logs -f air_air-caddy
~~~

Back up the persistent air_data, caddy_data and caddy_config volumes. Test restore before storing broker credentials. Maintain a secure backup of the Fernet credential key and the Android signing keystore. Loss of either can permanently prevent recovery of encrypted broker credentials or future in-place APK upgrades.

For GitHub-controlled immutable image builds and gated deployment, also follow GITHUB_DEPLOYMENT.md. The initial local installer deploys locally; it does not configure a GitHub SSH deploy key or deploy secrets.


## Admin-only broker account administration

Broker account ownership is controlled by an approved AIR operator identity. In the Android app, open **Admin → Broker Account Control** to assign multiple accounts per broker to a customer's approved E.164 mobile identity, save encrypted credentials, and remove accounts. Customers can only view accounts assigned to their own identity in AIR Connections.

The customer-facing account creation, credential-save, and removal API routes also require operator authorization. Hiding controls in the app is not the security boundary: direct customer API calls are rejected by the backend. Removing an account also removes its encrypted credential record. Account assignment does not enable order placement; execution permissions remain disabled until a broker authorization flow is separately verified.


## Mandatory NSE historical data bootstrap

The AIR API now starts a background bootstrap for the previous three calendar months of official NSE CM and F&O UDiFF bhavcopy ZIP archives. This is enabled by default in Docker Swarm and stored on the persistent `air_data` volume:

- `/var/lib/air/nse_bhavcopy.sqlite3` — normalized, searchable CM and FO end-of-day records.
- `/var/lib/air/nse_archives/CM` and `/var/lib/air/nse_archives/FO` — original NSE ZIP archives retained for reprocessing.

The Home screen shows download progress and CM/FO record counts. Open the Data tab to search cash equities or filter F&O options and futures. The server refreshes after market close at 21:00 IST on weekdays, guided by NSE's official CM/FO trading calendar. The calendar is cached persistently and displayed in the Data Center. On every API restart, an idempotent recovery pass backfills missed CM/FO sessions from the last paired import while maintaining at least the rolling three-month window. For each eligible date, AIR reconciles the official NSE CSV's normalized record count against the app's import ledger and actual SQLite row count. If either CM or FO is partial/mismatched, AIR marks the date PARTIAL, removes both market datasets for that date, and re-downloads/re-imports the session. Expired FO cleanup is gated by strategy completion in all three paths: after the initial historical load, after the daily 21:00 IST post-market strategy replay, and after recovery has repaired a partial download and returned the data set to READY. The implemented EXPIRY78 and ORIGINAL366/RECOVERED replay engines run without sending Telegram alerts or placing orders. Only after that run succeeds does AIR snapshot missing daily OHLCV, traded quantity and underlying-close bars into matching strategy ledger evidence using symbol, expiry, strike and CE/PE, then purge contracts whose expiry is before the India-local current date; expiry-day contracts remain until the next day. If data is still PARTIAL/FAILED or a strategy replay fails, cleanup is deferred and the FO rows remain available for recovery. The per-session removal counter ensures later source-count reconciliation recognizes intentional removals. The snapshot enriches only evidence; it does not overwrite lifecycle classifications, entry/exit fields, quantity or stored P&L. The P&L calendar rebuilds outcomes from the preserved daily-bar evidence. Original NSE ZIPs remain retained for reprocessing. RECOVERY remains a deferred strategy view without an executable replay engine; EXPIRYSCAN continues to use its separate Dhan snapshot workflow. The mobile Data Center displays mismatch, repair and expired-row cleanup/snapshot counts, and refreshes its visible rows after reconciliation changes even when row totals remain equal. If NSE calendar access is temporarily unavailable, the last persisted calendar is used and the refresh warning is exposed in status. An operator can retry the bootstrap from the authenticated API if the NSE source was temporarily unavailable.

Allow several GB of free disk space for the initial history and ongoing data. The app can be opened while the background bootstrap runs, but the Data screen must show READY before treating the full three-month history as available. READY requires at least 45 paired CM/FO sessions and no failed archive downloads.

This is daily EOD bhavcopy history. It does not contain intraday candles, tick history, bid/ask history or full intraday option-chain snapshots. See `backend/NSE_DATA_SETUP.md` for API details, fields and data-quality boundaries.


## Broker instrument masters and execution policy

AIR refreshes configured broker instrument masters on weekdays at 07:00 IST. The operator can also run a refresh from **AIR Admin → Execution & Broker Masters**. A downloaded master is parsed and validated before an atomic provider/account snapshot replacement; failed or undersized downloads preserve the last known-good master. Successful replacement removes obsolete tokens for that broker account. The master includes broker token, symbol, exchange/segment, expiry, option type, strike, lot size and tick size where published.

Default master sources are configured for Dhan, Zerodha, Upstox and Angel One. FYERS requires official URL(s) in the Docker secret/environment JSON `AIR_BROKER_MASTER_URLS`, for example `{"fyers":["https://public.fyers.in/sym_details/NSE_CM.csv","https://public.fyers.in/sym_details/NSE_FO.csv"]}`; confirm the correct segment-specific file names with FYERS. Multiple official segment files are merged by token before the atomic snapshot update. Keep credentials and URLs out of source control.

Automatic execution policy is persistent and defaults to **OFF**. It has a master switch plus independent EXPIRY78, EXPIRYSCAN and RECOVERED switches. Effective automatic eligibility requires both the master and strategy switch to be ON. With the master OFF, strategy views remain available for manual handling. This policy does not itself enable live order submission: each broker account remains separately order-disabled until broker execution adapters, account authorization, risk controls, and explicit confirmation workflows are verified. No automatic orders are sent by this policy service.


Failover currently permits a secondary account on the same broker only. Cross-broker failover is deliberately rejected until AIR can prove a one-to-one contract mapping between the two vendors' different instrument tokens and symbols. This prevents a backup broker from receiving an invalid or wrong contract subscription.

## Cross-platform local startup and CI runner

The local application startup command is documented in the repository root README and LOCAL_SETUP.md. For a personal Windows 10/11 or supported Linux PC, run the one-command AIR setup utility described in [SELF_HOSTED_RUNNER.md](SELF_HOSTED_RUNNER.md). It handles runner registration, repository CI routing and PR #7 verification. Do not merge PR #7 until the backend and Android workflows pass on the current PR head.
