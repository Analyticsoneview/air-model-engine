"""AIR deployment profile contract and validation.

Profiles are declarative deployment metadata. They never contain credentials or secrets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(__file__).resolve().parents[1] / "config" / "deployment_profiles"
SUPPORTED_PROFILES = {
    "onprem-single",
    "aws-private-single",
    "aws-saas-multi",
}
REQUIRED_SERVICES = {
    "frontend", "fastapi", "postgresql", "redis", "rabbitmq",
    "workflow_engine", "background_workers", "scheduler", "monitoring", "storage",
}


class DeploymentProfileError(ValueError):
    """Raised when a deployment profile is incomplete or internally inconsistent."""


def validate_profile(data: dict[str, Any], *, require_cloud_env: bool = False) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DeploymentProfileError("Deployment profile must be a JSON object")
    profile_id = data.get("profile_id")
    if profile_id not in SUPPORTED_PROFILES:
        raise DeploymentProfileError(f"Unsupported AIR deployment profile: {profile_id!r}")
    if data.get("schema_version") != 1:
        raise DeploymentProfileError("Unsupported AIR deployment profile schema_version")
    deployment = data.get("deployment")
    infrastructure = data.get("infrastructure")
    services = data.get("services")
    if not isinstance(deployment, dict):
        raise DeploymentProfileError("Profile deployment settings must be an object")
    if not isinstance(infrastructure, dict):
        raise DeploymentProfileError("Profile infrastructure settings must be an object")
    if not isinstance(services, dict):
        raise DeploymentProfileError("Profile services must be an object")

    missing_services = sorted(REQUIRED_SERVICES - set(services))
    if missing_services:
        raise DeploymentProfileError(f"Profile is missing mandatory services: {', '.join(missing_services)}")
    disabled_services = sorted(name for name in REQUIRED_SERVICES if services.get(name) is not True)
    if disabled_services:
        raise DeploymentProfileError(f"Mandatory AIR services cannot be disabled: {', '.join(disabled_services)}")
    if infrastructure.get("message_broker") not in {"rabbitmq", "amazon_mq_rabbitmq"}:
        raise DeploymentProfileError("RabbitMQ is mandatory for every AIR deployment profile")

    provider = deployment.get("provider")
    tenancy = deployment.get("tenancy")
    orchestrator = deployment.get("orchestrator")
    if profile_id == "onprem-single":
        if provider != "on_prem" or tenancy != "single":
            raise DeploymentProfileError("onprem-single must be on_prem and single-tenant")
        if orchestrator not in {"docker_compose", "docker_swarm"}:
            raise DeploymentProfileError("On-premises AIR requires Docker Compose or Docker Swarm")
        if infrastructure.get("storage") != "local":
            raise DeploymentProfileError("On-premises AIR must use local persistent storage")
    elif profile_id == "aws-private-single":
        if provider != "aws" or tenancy != "single":
            raise DeploymentProfileError("aws-private-single must be AWS single-tenant")
        if orchestrator not in {"ecs_fargate", "ecs_ec2"}:
            raise DeploymentProfileError("Private AWS AIR requires ECS; Kubernetes is not supported")
        if infrastructure.get("isolation") != "dedicated":
            raise DeploymentProfileError("Private AWS resources must be dedicated to the customer")
        if infrastructure.get("storage") != "efs_s3":
            raise DeploymentProfileError("Private AWS requires persistent EFS working storage and S3 backup storage")
    elif profile_id == "aws-saas-multi":
        if provider != "aws" or tenancy != "multi":
            raise DeploymentProfileError("aws-saas-multi must be AWS multi-tenant")
        if orchestrator not in {"ecs_fargate", "ecs_ec2"}:
            raise DeploymentProfileError("AIR SaaS requires ECS; Kubernetes is not supported")
        if infrastructure.get("isolation") != "tenant_scoped":
            raise DeploymentProfileError("AWS SaaS requires tenant-scoped isolation")
        if infrastructure.get("storage") != "efs_s3":
            raise DeploymentProfileError("AWS SaaS requires persistent EFS working storage and S3 object storage")

    if provider == "aws" and require_cloud_env and not (
        os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or deployment.get("region")
    ):
        raise DeploymentProfileError("AWS_REGION must be configured before AWS provisioning")
    return data


def load_runtime_profile() -> dict[str, Any]:
    """Load the selected profile and ensure container environment matches it."""
    profile = load_profile()
    deployment = profile["deployment"]
    expected = {
        "AIR_DEPLOYMENT_MODE": deployment["provider"],
        "AIR_TENANCY_MODE": deployment["tenancy"],
    }
    for key, value in expected.items():
        configured = os.getenv(key)
        if configured and configured != value:
            raise DeploymentProfileError(
                f"{key}={configured!r} conflicts with profile {profile['profile_id']!r} ({value!r})"
            )
    return profile


def load_profile(profile_id: str | None = None, *, require_cloud_env: bool = False) -> dict[str, Any]:
    profile_id = profile_id or os.getenv("AIR_DEPLOYMENT_PROFILE", "onprem-single")
    if profile_id not in SUPPORTED_PROFILES:
        raise DeploymentProfileError(f"Unsupported AIR deployment profile: {profile_id}")
    path = PROFILE_DIR / f"{profile_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DeploymentProfileError(f"Deployment profile file not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise DeploymentProfileError(f"Deployment profile JSON is invalid: {path.name}") from exc
    return validate_profile(data, require_cloud_env=require_cloud_env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an AIR deployment profile")
    parser.add_argument("--profile", default=os.getenv("AIR_DEPLOYMENT_PROFILE", "onprem-single"))
    parser.add_argument("--require-cloud-env", action="store_true")
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile, require_cloud_env=args.require_cloud_env)
    except DeploymentProfileError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": "VALID",
        "profile_id": profile["profile_id"],
        "provider": profile["deployment"]["provider"],
        "tenancy": profile["deployment"]["tenancy"],
        "orchestrator": profile["deployment"]["orchestrator"],
        "rabbitmq": "MANDATORY",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
