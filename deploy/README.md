# AIR deployment profiles and Deployment Manager

AIR is one product and one application codebase with deployment-specific profiles. The on-premises path does not require an AWS account, AWS credentials, cloud services or Kubernetes.

| Profile | Tenancy | Runtime | Data and messaging |
|---|---|---|---|
| `onprem-single` | Single tenant | Docker Compose or Docker Swarm | Local PostgreSQL, Redis, RabbitMQ and persistent volumes |
| `aws-private-single` | Single tenant | AWS ECS | Dedicated AWS environment with RDS, ElastiCache, Amazon MQ, EFS and S3 |
| `aws-saas-multi` | Multiple tenants | Shared AWS ECS runtime | Shared RDS PostgreSQL with tenant RLS, shared Redis with tenant-scoped keys/quotas, per-tenant S3 buckets, RabbitMQ vhosts/users and tenant Secrets Manager credentials |

## On-premises entry points

- Windows: `.\AIRDEPLOY.ps1 -DeploymentProfile onprem-single`
- Linux/macOS: `bash AIRDEPLOY.sh onprem-single`
- Direct local startup remains available through `AIRSTART.ps1` or `bash AIRSTART.sh`.
- Docker Swarm deployment uses `docker-stack.yml` and `deploy/deploy-swarm.sh`.

The on-premises installer creates missing local-only secrets without overwriting existing non-empty secrets, starts PostgreSQL, Redis, RabbitMQ, FastAPI, the workflow worker and PWA, then waits for service health and the API's full `/ready` response. The default installation readiness gate includes the configured 12-month NSE history bootstrap and healthy workflow runtime. Do not treat `/health` alone as full installation readiness.

## Validation boundaries

Pull-request CI validates profile contracts, renders Compose and Swarm configuration, checks shell/PowerShell syntax, and boots the complete Docker Compose service set in an isolated GitHub Actions runner. The runtime smoke test checks PostgreSQL/Redis/RabbitMQ, API and PWA health, and a fresh RabbitMQ-connected workflow-worker heartbeat. It deliberately disables the long NSE history bootstrap so CI remains bounded and does not claim full `/ready` acceptance.

A real customer-host Docker Swarm deployment, persistent-volume backup/restore drill, TLS/DNS validation and full 12-month NSE bootstrap remain deployment-environment acceptance activities. They are tracked as deferred readiness work until an on-prem host is available; they do not block code implementation or CI runtime validation.

## AWS deployment boundary

AWS profiles and provisioning code are implemented and validated in CI. **Live AWS provisioning is deferred** until an AWS account, region, credentials, remote Terraform state/locking, certificate and approved budget are available. CI does not apply Terraform or create AWS resources.

The private AWS profile uses dedicated infrastructure. The SaaS profile uses a shared application/database runtime with PostgreSQL row-level security and tenant-specific S3/RabbitMQ/Secrets Manager namespaces; it does not create a separate RDS database or ECS service for every tenant.

## Security

Deployment profile JSON files contain infrastructure choices only. Never store passwords, access keys, JWT secrets, database URLs or broker credentials in profile files or source control. On-premises credentials are supplied through file-backed Compose secrets or external Docker Swarm secrets. AWS runtime credentials are supplied through AWS Secrets Manager and task-role permissions.

## Release rules

- Do not enable public customer signup by default.
- Do not enable QOC capture or external broker integrations until customer credentials, entitlements and permissions are verified.
- Keep immutable image references for Swarm releases.
- Back up persistent data and test restore before storing production broker credentials.
- A passing CI runtime smoke test is not a production deployment or a substitute for full market-data readiness.
