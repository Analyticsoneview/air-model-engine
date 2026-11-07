# AIR installation and operations

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

If GitHub-hosted runner admission is unavailable because of account usage or billing limits, install the AIR runner on the Ubuntu host after the server is secured:

~~~bash
sudo bash /opt/air-model-engine/deploy/install-github-runner.sh
~~~

Generate a short-lived registration token from repository Settings → Actions → Runners → New self-hosted runner and enter it at the prompt. The script installs a dedicated airrunner account, Java 17, runner dependencies and the runner service. The runner belongs to the private AIR repository and receives Docker access for image builds; treat the host as a privileged CI machine.

After it appears online in GitHub, add this repository Actions variable:

~~~text
AIR_RUNNER_LABELS=["self-hosted","linux","x64","air"]
~~~

The CI workflows default to ubuntu-latest when this variable is absent. Once configured, backend tests, Docker builds, PWA builds and Android builds can use the self-hosted runner. The iOS lab workflow remains macOS-hosted.

## Android customer APK

Follow ANDROID_RELEASE.md to create and protect the AIR signing keystore and configure the five GitHub variable/secrets. Then run Actions → AIR Android Customer Release. Distribute only the signed APK artifact from a successful run, together with its SHA-256 checksum. Install and test it on real Android devices before customer rollout. The workflow is ARM64 only and does not publish to Google Play.

## Telegram and market-data activation

Telegram token and destination chat IDs can be entered during install. If omitted, a random placeholder secret is created and polling remains disabled. To replace the token later, run `sudo bash /opt/air-model-engine/deploy/rotate-telegram-secret.sh`. The helper creates a versioned Swarm secret, updates the stack and removes the old secret after the API service converges. Verify the bot's private and group chat IDs independently. Then set AIR_TELEGRAM_SCHEDULER_ENABLED=true in /etc/air/air.env and redeploy the stack. Verify the bot's private and group chat IDs independently.

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
