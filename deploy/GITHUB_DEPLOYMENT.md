# GitHub Actions deployment to the AIR Ubuntu server

This repository uses GitHub Actions to test and build immutable Docker images, GitHub Container Registry (GHCR) to store them, and your own Ubuntu Docker Swarm manager to run them. GitHub is the deployment controller; it is not the application host.

## Deployment safety

- Pull requests and normal pushes do not deploy to the production server.
- Pushes to \`main\` run verification and publish versioned images to GHCR.
- A deployment happens only when an administrator manually starts **AIR Build and Deploy** from the Actions tab on \`main\` and sets \`deploy=true\`.
- The deployment uses the exact commit SHA as the image tag, not the mutable \`latest\` tag.
- The server-side script checks Swarm state, required secrets and service convergence before reporting success.
- The first deployment must be prepared and smoke-tested manually. Do not enable scheduled AIR market-data jobs until broker credentials, entitlements and permissions are verified.

## GitHub repository configuration

### Repository variable

Add this under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Value |
|---|---|
| \`AIR_API_BASE_URL\` | Public HTTPS API base URL, e.g. \`https://api.your-domain.example\` |

This URL is compiled into the Flutter PWA. Do not use localhost.

### Repository secrets

Add these under **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Meaning |
|---|---|
| \`DEPLOY_HOST\` | Public IP or DNS name of your Ubuntu server |
| \`DEPLOY_USER\` | Dedicated SSH deployment user |
| \`DEPLOY_SSH_KEY\` | Private SSH key for that user; never commit it |
| \`DEPLOY_KNOWN_HOSTS\` | Verified SSH host-key line for the server |
| \`DEPLOY_PATH\` | Absolute path to the dedicated deployment checkout, e.g. \`/opt/air-model-engine\` |

Use a dedicated SSH key and a restricted deployment account. Do not use your personal SSH private key. The SSH account needs only the permissions required to update this checkout and run the approved Docker deployment commands. Docker access is effectively root access; protect this account accordingly.

## One-time Ubuntu preparation (perform later on the server)

1. Install Docker Engine and the Docker Compose plugin, initialize Swarm on the manager, and configure firewall rules.
2. Create a dedicated deployment account and add its public key to \`authorized_keys\`.
3. Give the server a **read-only GitHub deploy key** so it can fetch this private repository. Clone the repository to the path configured in \`DEPLOY_PATH\`; keep this checkout dedicated to deployment (no local edits).
4. Create a GitHub Personal Access Token with only \`read:packages\` for the server's GHCR login. On the server, run \`echo 'TOKEN' | docker login ghcr.io -u GITHUB_USERNAME --password-stdin\`. Do not put this token in the repository or in this chat.
5. Create the Docker Swarm secrets listed below.
6. Create \`/etc/air/air.env\`, owned by root and mode \`0600\`, with the required non-secret runtime values. Never put bot tokens, JWT secrets, encryption keys or admin API keys in this file.

Example \`/etc/air/air.env\` (replace placeholders; values are examples, not working credentials):

\`\`\`bash
AIR_OPERATOR_CUSTOMER_IDS="+919876543210"
AIR_CORS_ORIGINS="https://app.your-domain.example"
AIR_API_PORT=8000
AIR_TELEGRAM_CHAT_IDS="<verified-private-chat-id>,<verified-negative-group-chat-id>"
AIR_TELEGRAM_SCHEDULER_ENABLED=false
AIR_QOC_SCHEDULER_ENABLED=false
AIR_QOC_DHAN_AUTO_RENEW_ENABLED=false
AIR_QOC_DHAN_ACCOUNT_ID=""
AIR_QOC_DHAN_UNDERLYINGS='[]'
AIR_EXPIRYSCAN_MAX_DTE=45
AIR_EXPIRYSCAN_MAX_ROWS=2000
\`\`\`

Do not set \`AIR_BACKEND_IMAGE\` or \`AIR_PWA_IMAGE\` in this file; the workflow supplies immutable image references for each deployment.

### Required Swarm secrets

The current \`docker-stack.yml\` expects all four external secrets:

- \`air_jwt_secret\`
- \`air_credential_key\`
- \`air_admin_api_key\`
- \`air_telegram_bot_token\`

Follow [DOCKER_SWARM.md](./DOCKER_SWARM.md) for generation of the first three. Create the Telegram secret locally on the Swarm manager using the replacement BotFather token:

\`\`\`bash
read -rsp "Telegram bot token: " AIR_TELEGRAM_BOT_TOKEN; echo
printf '%s' "$AIR_TELEGRAM_BOT_TOKEN" | docker secret create air_telegram_bot_token -
unset AIR_TELEGRAM_BOT_TOKEN
\`\`\`

The token is entered directly on the server terminal and is not committed to GitHub. Verify the group ID from Telegram's \`getUpdates\` response; use the exact signed \`chat.id\`. Do not assume the group ID is positive.

## First deployment procedure

After the one-time server preparation is complete:

1. Confirm the default branch contains the reviewed deployment workflow and Docker stack.
2. Confirm the GHCR images are visible to the server's read-only package credential.
3. Open **Actions → AIR Build and Deploy → Run workflow** on \`main\`.
4. Leave \`deploy=false\` for a build-only run. Select \`deploy=true\` only after the server setup and all secrets are ready.
5. Review the job logs. A successful deploy job means both Swarm services converged to one replica; it does not by itself prove external DNS, TLS, login, database persistence or Telegram delivery.

## Post-deployment smoke tests

From a trusted network, verify:

- API health endpoint: \`https://api.your-domain.example/health\`
- PWA loads over HTTPS and can reach the configured API URL.
- Operator login and access-control flows work.
- A test record survives an API service restart (confirm persistent \`air_data\` volume).
- Authenticated operator call \`POST /api/v1/model-engine/telegram/test\` reports two successful destinations and no failures; also visually confirm delivery in both private chat and the AIR group.
- \`docker service ls\` shows \`air_air-api\` and \`air_air-pwa\` as \`1/1\`.
- Backups and restore have been tested.

## Important current architecture limits

- The current Swarm file is a single-node, single-replica lab topology. SQLite and process-local OAuth state are not ready for multiple API replicas.
- The API port 8000 is private on the Docker overlay and is reachable through Caddy only.
- Configure a TLS reverse proxy to route the app hostname to \`air-pwa:8080\` and the API hostname to \`air-api:8000\`.
- Keep \`AIR_QOC_SCHEDULER_ENABLED\` and \`AIR_TELEGRAM_SCHEDULER_ENABLED\` off until the first production smoke tests and broker/data checks pass.
- No broker order placement is enabled by this deployment. Research alerts are not broker orders.
- The deployment script reports service replica convergence. It does not automatically roll back on every application-level smoke-test failure; retain the previous immutable image tags so a rollback can be performed deliberately.
