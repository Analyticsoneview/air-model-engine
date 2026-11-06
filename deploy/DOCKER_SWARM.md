# Self-hosted Docker Swarm deployment (single-node lab)

This stack is a **single-replica lab deployment**, not a highly available production cluster. The current authentication, account, credential and order stores are SQLite and OAuth state is process-local. Do not scale the API service above one replica until the database and one-time OAuth state are migrated to shared durable services.

## 1. Build the API image

From the repository root:

```bash
docker build -t air-model-engine-api:lab ./backend
```

For a multi-node Swarm, push the image to a private registry and set `AIR_BACKEND_IMAGE` to that immutable image reference.

## 2. Create Docker secrets

Generate a JWT secret and Fernet key on the server. Keep both outside source control and do not paste them into chat.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | docker secret create air_jwt_secret -
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | docker secret create air_credential_key -
```

Back up the Fernet key securely. Losing it makes encrypted broker credentials unrecoverable. Rotating it requires a planned re-encryption migration.

## 3. Set deployment variables

```bash
export AIR_OPERATOR_CUSTOMER_IDS="<provisioned-customer-uuid>"
export AIR_API_PORT=8000
export AIR_BACKEND_IMAGE=air-model-engine-api:lab
```

For Angel One, configure the actual server client local IP, public IP and MAC address as `AIR_CLIENT_LOCAL_IP`, `AIR_CLIENT_PUBLIC_IP` and `AIR_CLIENT_MAC_ADDRESS`. Do not use placeholder values.

## 4. Deploy

```bash
docker stack deploy -c docker-stack.yml air
docker service ls
docker service logs -f air_air-api
```

Health check: `http://<server-host>:8000/health`.

## 5. Security and production blockers

- Put the API behind a TLS reverse proxy and firewall the published port to trusted ingress only.
- Configure backups for the `air_data` volume and test restore before storing broker credentials.
- The example publishes the API port for lab connectivity; it does not configure TLS or internet-facing ingress.
- SQLite plus in-memory OAuth state requires one replica. PostgreSQL, Redis-backed OAuth state, migrations, shared audit storage and HA deployment are not implemented in this stack.
- Broker API plans, data entitlements, static IP approvals, instrument masters and exchange data redistribution rights must be verified separately.
- No live order permission is enabled by this deployment.
