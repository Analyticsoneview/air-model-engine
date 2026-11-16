# AIR enterprise licensing and deployment binding

## Design

AIR remains one product with multiple deployment profiles. Enterprise licences are issued against an organisation's active annual B2B commercial contract and are bound to a registered AIR deployment instance.

Supported deployment profiles:
- `onprem-single` — on-premises Docker Compose or Docker Swarm; local PostgreSQL, Redis, RabbitMQ and storage.
- `aws-private-single` — future dedicated AWS deployment on ECS.
- `aws-saas-multi` — future AWS multi-tenant deployment on ECS.

No AWS API, AWS account, cloud callback or external licensing service is required to validate an on-premises licence.

## Signing and offline verification

The issuer signs a canonical JSON licence payload with Ed25519. The signing private key belongs only to the controlled licence-issuing environment. AIR installations receive only the Ed25519 public verification key and signed licence token.

Issuer secret:
- `AIR_LICENSE_SIGNING_PRIVATE_KEY` — base64url-encoded 32-byte Ed25519 private key. Never put this in an AIR customer installation, image, repository or deployment bundle.

AIR runtime configuration:
- `AIR_LICENSE_VERIFY_PUBLIC_KEY` — base64url-encoded 32-byte Ed25519 public key.
- `AIR_ENTERPRISE_LICENSE_TOKEN` — signed licence token delivered to the installation.
- `AIR_TENANT_ID` — organisation tenant identifier.
- `AIR_DEPLOYMENT_INSTANCE_ID` — registered deployment identifier.
- `AIR_DEPLOYMENT_PROFILE` — one of the supported deployment profile identifiers.
- `AIR_DEPLOYMENT_FINGERPRINT` — stable installation fingerprint used when the deployment was registered.

These values should be injected using the installation's secret/configuration mechanism (Docker secrets for secret values); do not store private signing material in Docker images.

## Lifecycle

1. Register an organisation-owned deployment instance with a stable instance key, supported profile and fingerprint.
2. Create and activate the annual B2B contract in the existing commercial contract ledger.
3. Issue a licence against that active contract and a registered deployment. Issuance records the seat ceiling, deployment ceiling, plan entitlements, allowed deployment profile and validity dates.
4. The issuer returns a signed licence token. The customer installation validates it locally using the public key.
5. Feature gates treat an installed enterprise licence as authoritative. Invalid or expired enterprise tokens fail closed and do not fall back to a personal subscription or operator override.
6. Organisation invitations and seat accounting use the lower of the organisation quota and active enterprise licence seat ceiling.
7. Revocation is recorded in the central licence ledger and blocks future issuance/status operations. Since an offline installation cannot receive an immediate remote revocation, revoke takes effect there when the installation receives an updated signed licence/revocation package or the existing token reaches its expiry/grace boundary. This is an explicit offline-operability trade-off.

## Security and operational boundaries

- Licence payloads bind tenant, contract, deployment ID, profile ID and SHA-256 deployment fingerprint.
- Altered payloads, wrong organisation/deployment/profile/fingerprint, restricted features, not-yet-valid licences and expired licences are rejected.
- Grace period is explicit and bounded by the signed `grace_until` date.
- Seat and deployment limits are validated at issuance; membership operations enforce the effective seat ceiling.
- All licensing persistence is tenant-scoped and protected by PostgreSQL RLS. Licence lifecycle events are append-only.
- Payment collection and public pricing remain disabled; this gate does not enable billing providers or auto-renewal charging.
- AWS profiles are validated as future deployment targets only. No AWS infrastructure or credentials are provisioned by this gate.

## API surface

- `POST /api/v1/enterprise-licensing/deployments/register`
- `POST /api/v1/enterprise-licensing/licenses/issue`
- `POST /api/v1/enterprise-licensing/licenses/{license_id}/revoke`
- `GET /api/v1/enterprise-licensing/deployments/{deployment_id}/status`
- `POST /api/v1/enterprise-licensing/licenses/verify`

The issue/register/revoke/status routes require an AIR licensing operator identity. Verification requires an authenticated customer and checks the authenticated organisation context.
