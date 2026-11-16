# AIR private AWS single-tenant deployment

This Terraform root module provisions a dedicated AWS environment for one AIR customer. It is intentionally separate from the AWS SaaS multi-tenant architecture.

## Included infrastructure

- Dedicated VPC with two public and two private subnets across two availability zones, NAT gateways and private routing.
- Public ALB with HTTPS when an ACM certificate is supplied. Plain HTTP is disabled by default and requires explicit allow_http=true for temporary testing.
- Private ECS Fargate cluster and task definitions for FastAPI, RabbitMQ workflow worker and PWA. Service creation is opt-in through deploy_services=true.
- Private encrypted RDS PostgreSQL, Multi-AZ ElastiCache Redis with TLS/authentication, and private multi-AZ Amazon MQ RabbitMQ.
- Encrypted EFS working storage with access point and backup policy, plus private/versioned S3 object storage.
- ECR repositories with immutable tags and image scanning.
- Secrets Manager runtime credentials, CloudWatch log groups and least-privilege task/execution roles.

## Safe workflow

1. Configure Terraform state storage separately and review the state-backend policy.
2. Supply an AWS region and inspect the proposed resource plan.
3. Apply infrastructure only after an authorized operator approves the cost and security review.
4. Build and scan the backend and PWA images, push immutable tags to the generated ECR repositories.
5. Supply the image URIs, ACM certificate ARN and deploy_services=true for the service rollout.
6. Validate /health, /ready, RabbitMQ workflow heartbeat, data bootstrap and application smoke tests.

The default deploy_services=false creates no ECS task definitions or services. Terraform itself is never applied by GitHub Actions. No AWS account resources are created by CI.

## Required variables

At minimum, set aws_region. Before enabling services, provide backend_image_uri, pwa_image_uri, and either acm_certificate_arn or the explicit temporary-test flag allow_http=true.

## Operational cautions

- Terraform state contains generated credentials and secret values. Use an encrypted, access-restricted remote state bucket with locking, and never commit state or plan files.
- Review the current AWS service quotas and regional engine-version availability before applying.
- NAT gateways, Multi-AZ databases/brokers, ALB, EFS, backups and data transfer incur charges.
- This gate creates dedicated single-tenant infrastructure only. It does not implement SaaS tenant provisioning or cross-tenant isolation.
- Initial NSE/CM/FO historical-data download and AIR research readiness must be verified by the deployed installation workflow; Terraform success is not application readiness.
