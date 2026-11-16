# AIR AWS deployment — private single-tenant and SaaS multi-tenant

This Terraform root provisions the shared AWS infrastructure used by AIR's two AWS deployment profiles. The application, APIs, workflow engine and deployment manager remain one codebase; the selected profile changes the infrastructure and tenant isolation model.

## Deployment profiles

| Profile | Tenancy | Isolation model | Runtime |
|---|---|---|---|
| `aws-private-single` | One customer per environment | Dedicated VPC, RDS, Redis, RabbitMQ, EFS/S3 and ECS services | Dedicated AIR API, worker and PWA |
| `aws-saas-multi` | Multiple customers in one environment | Shared RDS with PostgreSQL RLS, shared Redis with tenant-scoped keys/quotas, shared ECS runtime, per-tenant S3 buckets, RabbitMQ vhosts/users and Secrets Manager credentials | One tenant-aware AIR API and workflow runtime |

For SaaS, the database and ECS application services are shared by design. PostgreSQL row-level security and tenant context isolate customer rows. The worker routes each tenant's workflow events through its provisioned RabbitMQ vhost. Tenant data objects use a dedicated S3 bucket with public access blocked, encryption, versioning and a TLS-only bucket policy.

## Shared infrastructure

- VPC with two public and two private subnets across two availability zones, NAT gateways and private routing.
- Public ALB with HTTPS when an ACM certificate is supplied. Plain HTTP is disabled by default and requires explicit `allow_http=true` for temporary testing.
- Private ECS Fargate cluster and task definitions for FastAPI, RabbitMQ workflow worker and PWA. Service creation is opt-in through `deploy_services=true`.
- Encrypted RDS PostgreSQL, Multi-AZ ElastiCache Redis with TLS/authentication, and private multi-AZ Amazon MQ RabbitMQ.
- Encrypted EFS working storage and shared S3 backup/object storage.
- ECR repositories with immutable tags and image scanning.
- Secrets Manager runtime credentials, CloudWatch log groups and least-privilege task/execution roles.

## SaaS tenant provisioning lifecycle

1. An administrator creates a tenant through `POST /api/v1/admin/tenants`. In `aws-saas-multi`, it remains `PROVISIONING` and cannot be used by customers yet.
2. An authorized administrator calls `POST /api/v1/admin/tenants/{tenant_id}/provision`.
3. The AWS adapter idempotently creates the tenant's private S3 bucket, RabbitMQ vhost and restricted RabbitMQ user, and a Secrets Manager secret containing that tenant's RabbitMQ credentials and Fernet credential-encryption key.
4. The tenant registry records the resource identifiers and provisioning timestamp. Only after successful provisioning does the tenant become `ACTIVE`.
5. The workflow worker discovers active, provisioned tenants and publishes/consumes workflow events in the matching tenant vhost. PostgreSQL RLS remains the authoritative data isolation boundary.
6. Suspending or closing a tenant revokes its RabbitMQ vhost permissions while retaining its S3 bucket and Secrets Manager secret for controlled retention/recovery. Reactivation restores access.
7. Tenant member limits are checked by the registry; daily authenticated API calls are counted in Redis; S3 object writes are checked against the tenant's storage quota.

A failed provisioning attempt remains `PROVISIONING` with a bounded error code and can be retried. The adapter does not silently mark a tenant ready when one of its required AWS resources is missing.

## Required runtime settings for SaaS

Terraform supplies these settings to the API and worker tasks:

- `AIR_DEPLOYMENT_PROFILE=aws-saas-multi` and `AIR_TENANCY_MODE=multi`
- `AIR_RABBITMQ_MANAGEMENT_URL`, `AIR_RABBITMQ_ADMIN_USER` and the Secrets Manager-backed `AIR_RABBITMQ_ADMIN_PASSWORD`
- `AIR_TENANT_S3_BUCKET_PREFIX` and `AIR_TENANT_SECRETS_PREFIX`
- `AWS_REGION` and the shared RDS/Redis/RabbitMQ connection secrets

The ECS task role is scoped to the configured tenant bucket prefix and tenant Secrets Manager path. RabbitMQ management port 15671 is reachable only from the ECS security group; it is not public.

## Safe workflow

1. Configure encrypted remote Terraform state and locking separately.
2. Supply an AWS region and choose `deployment_profile` plus the matching `tenancy_mode`.
3. Inspect the Terraform plan and obtain an authorized cost/security approval.
4. Apply shared infrastructure only from an authorized deployment environment.
5. Build and scan the backend and PWA images, then push immutable tags to the generated ECR repositories.
6. Supply image URIs, an ACM certificate ARN and `deploy_services=true` for the service rollout.
7. Verify /health, /ready, workflow worker heartbeat, RabbitMQ connectivity, PostgreSQL migrations, initial market-data bootstrap and application smoke tests.
8. For SaaS, provision each existing/new tenant through the admin provisioning endpoint and verify its resource metadata before allowing customer access.

The default `deploy_services=false` creates no ECS task definitions or services. Terraform validation in GitHub Actions does not apply infrastructure or create AWS resources.

## Required variables and operational cautions

At minimum, set `aws_region`. Before enabling services, provide backend and PWA image URIs, and either an ACM certificate ARN or the explicit temporary-test flag `allow_http=true`.

- Terraform state contains generated credentials and secret values. Use an encrypted, access-restricted remote state bucket with locking; never commit state or plan files.
- Set a unique `environment_name` for each AWS environment. Tenant bucket names are derived from this name and the AWS account ID.
- Review AWS service quotas, regional engine-version availability and the cost of NAT gateways, Multi-AZ databases/brokers, ALB, EFS, backups and data transfer before applying.
- Existing customer tenants created by the Gate 14 migration must be provisioned before enabling SaaS customer access.
- Initial NSE/CM/FO historical-data download and AIR research readiness are separate release gates; Terraform success is not application readiness.
- CI validates Terraform and the provisioner contract. It does not prove an actual AWS apply, live service health or production IAM configuration. Those require an authorized AWS deployment and acceptance run.
