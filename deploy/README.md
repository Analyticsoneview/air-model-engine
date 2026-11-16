# AIR deployment profiles and Deployment Manager

AIR is one application codebase with three deployment profiles:

| Profile | Tenancy | Orchestration | Data / messaging |
|---|---|---|---|
| `onprem-single` | Single tenant | Docker Compose; Docker Swarm supported | Local PostgreSQL, Redis, RabbitMQ and storage |
| `aws-private-single` | Single tenant | AWS ECS | Dedicated RDS PostgreSQL, ElastiCache Redis, Amazon MQ RabbitMQ and S3 |
| `aws-saas-multi` | Multi tenant | AWS ECS | Tenant-scoped RDS, Redis, RabbitMQ routing and S3 access |

## Entry points

- Windows: `AIRDEPLOY.ps1 -Profile onprem-single`
- Linux: `./AIRDEPLOY.sh onprem-single`
- Legacy local entry points `AIRSTART.ps1` and `AIRSTART.sh` remain supported.

The profile validator is packaged in the backend source and uses Python's standard library only. The Deployment Manager invokes it through a disposable Python container, so a host Python installation is not required.

## Mandatory services

Every profile requires the frontend, FastAPI, PostgreSQL, Redis, RabbitMQ, workflow engine, background workers, scheduler, monitoring and persistent storage. RabbitMQ cannot be disabled by a profile.

## Security

Profile files contain infrastructure choices only. They must never contain passwords, access keys, JWT secrets, database URLs or broker credentials. On-premises secrets remain Docker secrets. AWS secrets are provisioned through the AWS adapter using AWS Secrets Manager.

## Current delivery boundary

Gate 12 establishes the common profile contract and the on-premises one-click route. The AWS profiles are defined and validated, but their provisioning adapters are delivered in the subsequent private-AWS and SaaS deployment gates. Selecting an AWS profile before its adapter is available fails closed and creates no AWS resources.
