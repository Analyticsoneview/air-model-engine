"""AWS resource provisioning for AIR SaaS tenants.

The application remains shared; tenant data, RabbitMQ transport and runtime
credentials receive deterministic tenant-specific namespaces. Operations are
idempotent so a failed onboarding can be retried safely.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx
from cryptography.fernet import Fernet


class TenantInfrastructureError(RuntimeError):
    """Raised when a tenant's AWS infrastructure cannot be provisioned safely."""


def _secret_value(name: str, default: str = "") -> str:
    file_path = os.getenv(name + "_FILE", "").strip()
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    return os.getenv(name, default).strip()


class AwsTenantProvisioner:
    """Provision isolated S3 bucket, RabbitMQ vhost and Secrets Manager secret."""

    def __init__(
        self,
        *,
        s3_client,
        secrets_client,
        http_client: httpx.Client,
        bucket_prefix: str,
        secrets_prefix: str,
        rabbitmq_admin_user: str,
        region: str,
    ):
        self.s3 = s3_client
        self.secrets = secrets_client
        self.http = http_client
        self.bucket_prefix = bucket_prefix.strip()
        self.secrets_prefix = secrets_prefix.strip("/")
        self.rabbitmq_admin_user = rabbitmq_admin_user.strip()
        self.region = region.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,29}-", self.bucket_prefix):
            raise ValueError("AIR_TENANT_S3_BUCKET_PREFIX must be 4-31 lowercase letters/digits/hyphens and end with '-'")
        if not self.secrets_prefix or not self.rabbitmq_admin_user or not self.region:
            raise ValueError("AWS tenant provisioning configuration is incomplete")

    @classmethod
    def from_environment(cls) -> "AwsTenantProvisioner":
        if os.getenv("AIR_DEPLOYMENT_PROFILE", "onprem-single") != "aws-saas-multi":
            raise TenantInfrastructureError("AWS tenant provisioning is available only in aws-saas-multi profile")
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "")
        management_url = os.getenv("AIR_RABBITMQ_MANAGEMENT_URL", "").strip()
        admin_user = os.getenv("AIR_RABBITMQ_ADMIN_USER", os.getenv("AIR_RABBITMQ_USER", "air")).strip()
        admin_password = _secret_value("AIR_RABBITMQ_ADMIN_PASSWORD") or _secret_value("AIR_RABBITMQ_PASSWORD")
        if not region or not management_url or not admin_user or not admin_password:
            raise TenantInfrastructureError(
                "AWS_REGION, AIR_RABBITMQ_MANAGEMENT_URL and RabbitMQ management credentials are required"
            )
        try:
            import boto3
        except ImportError as exc:
            raise TenantInfrastructureError("boto3 is required by the AWS SaaS deployment image") from exc
        session = boto3.session.Session(region_name=region)
        return cls(
            s3_client=session.client("s3"),
            secrets_client=session.client("secretsmanager"),
            http_client=httpx.Client(
                base_url=management_url.rstrip("/"),
                auth=(admin_user, admin_password),
                timeout=httpx.Timeout(15.0),
                verify=True,
            ),
            bucket_prefix=os.getenv("AIR_TENANT_S3_BUCKET_PREFIX", "air-tenant-"),
            secrets_prefix=os.getenv("AIR_TENANT_SECRETS_PREFIX", "air/tenants"),
            rabbitmq_admin_user=admin_user,
            region=region,
        )

    @staticmethod
    def _tenant_id(tenant: dict) -> str:
        value = str(tenant.get("tenant_id", "")).strip()
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("A valid tenant UUID is required for AWS provisioning") from exc

    def _bucket_name(self, tenant_id: str) -> str:
        name = self.bucket_prefix + tenant_id.replace("-", "")
        if len(name) > 63:
            raise ValueError("Tenant S3 bucket name exceeds the AWS 63-character limit")
        return name

    def _secret_name(self, tenant_id: str) -> str:
        return f"{self.secrets_prefix}/{tenant_id}/runtime"

    def _ensure_bucket(self, bucket: str, tenant_id: str, max_storage_bytes: int) -> None:
        exists = False
        try:
            self.s3.head_bucket(Bucket=bucket)
            exists = True
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            code = str(error.get("Code", ""))
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
                raise TenantInfrastructureError(f"Cannot verify tenant S3 bucket {bucket}") from exc
        if not exists:
            request = {"Bucket": bucket}
            if self.region != "us-east-1":
                request["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.s3.create_bucket(**request)
        self.s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        self.s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}],
            },
        )
        self.s3.put_bucket_versioning(
            Bucket=bucket, VersioningConfiguration={"Status": "Enabled"},
        )
        self.s3.put_bucket_ownership_controls(
            Bucket=bucket,
            OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
        )
        self.s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "DenyInsecureTransport",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:*",
                    "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }],
            }),
        )
        self.s3.put_bucket_tagging(
            Bucket=bucket,
            Tagging={"TagSet": [
                {"Key": "Product", "Value": "AIR"},
                {"Key": "TenantId", "Value": tenant_id},
                {"Key": "ManagedBy", "Value": "AIR-Tenant-Provisioner"},
                {"Key": "MaxStorageBytes", "Value": str(int(max_storage_bytes))},
            ]},
        )

    def _tenant_credentials(self, tenant_id: str, username: str) -> tuple[str, str]:
        name = self._secret_name(tenant_id)
        try:
            result = self.secrets.describe_secret(SecretId=name)
            secret = self.secrets.get_secret_value(SecretId=name)
            payload = json.loads(secret["SecretString"])
            password = str(payload["rabbitmq_password"])
            credential_key = str(payload["credential_key"])
            if payload.get("rabbitmq_username") != username:
                payload["rabbitmq_username"] = username
                payload["rabbitmq_password"] = password
                self.secrets.put_secret_value(SecretId=name, SecretString=json.dumps(payload, sort_keys=True))
            return str(result["ARN"]), password
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            code = str((response.get("Error", {}) if isinstance(response, dict) else {}).get("Code", ""))
            if code not in {"ResourceNotFoundException", "NotFound"}:
                raise TenantInfrastructureError(f"Cannot read tenant secret {name}") from exc
        password = secrets.token_urlsafe(36)
        credential_key = Fernet.generate_key().decode("ascii")
        payload = {
            "tenant_id": tenant_id,
            "rabbitmq_username": username,
            "rabbitmq_password": password,
            "credential_key": credential_key,
        }
        created = self.secrets.create_secret(
            Name=name,
            Description=f"AIR SaaS runtime credentials for tenant {tenant_id}",
            SecretString=json.dumps(payload, sort_keys=True),
            Tags=[{"Key": "Product", "Value": "AIR"}, {"Key": "TenantId", "Value": tenant_id}],
        )
        return str(created["ARN"]), password

    def _rabbitmq_request(self, method: str, path: str, *, json_body: dict | None = None) -> None:
        try:
            response = self.http.request(method, path, json=json_body)
            if response.status_code not in {200, 201, 204}:
                raise TenantInfrastructureError(
                    f"RabbitMQ management API returned HTTP {response.status_code}"
                )
        except httpx.HTTPError as exc:
            raise TenantInfrastructureError("RabbitMQ tenant namespace provisioning failed") from exc

    def _ensure_vhost(self, vhost: str, username: str, password: str) -> None:
        encoded_vhost = quote(vhost, safe="")
        encoded_user = quote(username, safe="")
        self._rabbitmq_request("PUT", f"/api/vhosts/{encoded_vhost}", json_body={})
        self._rabbitmq_request(
            "PUT", f"/api/users/{encoded_user}",
            json_body={"password": password, "tags": ""},
        )
        self._rabbitmq_request(
            "PUT", f"/api/permissions/{encoded_vhost}/{encoded_user}",
            json_body={"configure": ".*", "write": ".*", "read": ".*"},
        )

    def provision(self, tenant: dict) -> dict:
        tenant_id = self._tenant_id(tenant)
        vhost = str(tenant.get("rabbitmq_vhost", "")).strip()
        if not vhost or len(vhost) > 128:
            raise ValueError("Tenant RabbitMQ vhost is missing or invalid")
        bucket = self._bucket_name(tenant_id)
        username = "air-" + tenant_id.replace("-", "")[:24]
        max_storage_bytes = int(tenant.get("max_storage_bytes", 1073741824))
        self._ensure_bucket(bucket, tenant_id, max_storage_bytes)
        secret_arn, rabbit_password = self._tenant_credentials(tenant_id, username)
        self._ensure_vhost(vhost, username, rabbit_password)
        return {
            "status": "PROVISIONED",
            "tenant_id": tenant_id,
            "storage": {"provider": "s3", "bucket": bucket, "prefix": f"tenants/{tenant_id}/"},
            "messaging": {"provider": "amazon_mq_rabbitmq", "vhost": vhost, "username": username},
            "credentials_secret_arn": secret_arn,
            "quotas": {
                "max_members": int(tenant.get("max_members", 1)),
                "max_api_calls_per_day": int(tenant.get("max_api_calls_per_day", 10000)),
                "max_storage_bytes": max_storage_bytes,
            },
        }

    def enforce_storage_quota(self, tenant: dict, additional_bytes: int = 0) -> int:
        tenant_id = self._tenant_id(tenant)
        bucket = self._bucket_name(tenant_id)
        limit = int(tenant.get("max_storage_bytes", 1073741824))
        requested = int(additional_bytes)
        if requested < 0:
            raise ValueError("additional_bytes cannot be negative")
        paginator = self.s3.get_paginator("list_objects_v2")
        used = 0
        for page in paginator.paginate(Bucket=bucket):
            used += sum(int(item.get("Size", 0)) for item in page.get("Contents", []))
        if used + requested > limit:
            raise TenantInfrastructureError("Tenant storage quota would be exceeded")
        return used

    @staticmethod
    def _validate_object_key(key: str) -> str:
        value = str(key or "")
        if (
            not value or len(value) > 512 or len(value.encode("utf-8")) > 1024 or value.startswith("/")
            or "\\" in value or "\x00" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(not part or part in {".", ".."} for part in value.split("/"))
        ):
            raise ValueError("A safe tenant object key of 1-512 characters is required")
        return value

    def put_tenant_object(
        self, tenant: dict, key: str, body: bytes, *,
        content_type: str = "application/octet-stream",
        sha256: str | None = None,
        quota_prevalidated: bool = False,
    ) -> dict:
        tenant_id = self._tenant_id(tenant)
        object_key = self._validate_object_key(key)
        if not isinstance(body, bytes) or not body:
            raise ValueError("Tenant object body must contain bytes")
        digest = str(sha256 or __import__("hashlib").sha256(body).hexdigest()).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("A valid SHA-256 digest is required")
        size = len(body)
        used = 0 if quota_prevalidated else self.enforce_storage_quota(tenant, size)
        bucket = self._bucket_name(tenant_id)
        stored_key = f"tenants/{tenant_id}/{object_key}"

        # A pending database reservation can be retried after a process/network
        # failure. Verify an already-written S3 object before attempting another put.
        try:
            existing = self.s3.head_object(Bucket=bucket, Key=stored_key)
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(error.get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"} and status != 404:
                raise TenantInfrastructureError("Could not verify the tenant object before upload") from exc
        else:
            metadata = existing.get("Metadata", {}) or {}
            if int(existing.get("ContentLength", -1)) != size or metadata.get("sha256") != digest:
                raise TenantInfrastructureError("Tenant object key already contains different content")
            return {
                "bucket": bucket, "key": stored_key, "bytes": size,
                "previous_usage_bytes": used, "etag": str(existing.get("ETag", "")).strip('"'),
                "already_present": True,
            }

        try:
            result = self.s3.put_object(
                Bucket=bucket, Key=stored_key, Body=body,
                ContentType=content_type, ServerSideEncryption="AES256",
                Metadata={"sha256": digest},
                IfNoneMatch="*",
            )
        except Exception as exc:
            # Another retry may have won the conditional write after our HEAD.
            response = getattr(exc, "response", {}) or {}
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if str(error.get("Code", "")) not in {"PreconditionFailed", "412"} and status != 412:
                raise TenantInfrastructureError("Tenant object upload failed") from exc
            try:
                existing = self.s3.head_object(Bucket=bucket, Key=stored_key)
            except Exception as verify_exc:
                raise TenantInfrastructureError("Concurrent tenant object upload could not be verified") from verify_exc
            metadata = existing.get("Metadata", {}) or {}
            if int(existing.get("ContentLength", -1)) != size or metadata.get("sha256") != digest:
                raise TenantInfrastructureError("Tenant object key already contains different content") from exc
            result = existing
            already_present = True
        else:
            already_present = False
        return {
            "bucket": bucket, "key": stored_key, "bytes": size,
            "previous_usage_bytes": used, "etag": str(result.get("ETag", "")).strip('"'),
            "already_present": already_present,
        }

    def get_tenant_object(self, tenant: dict, key: str) -> dict:
        tenant_id = self._tenant_id(tenant)
        object_key = self._validate_object_key(key)
        bucket = self._bucket_name(tenant_id)
        stored_key = f"tenants/{tenant_id}/{object_key}"
        try:
            result = self.s3.get_object(Bucket=bucket, Key=stored_key)
            body = result["Body"].read()
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if str(error.get("Code", "")) in {"404", "NoSuchKey", "NotFound"} or status == 404:
                raise KeyError("Tenant object does not exist") from exc
            raise TenantInfrastructureError("Could not read the tenant object") from exc
        return {
            "body": body,
            "content_type": str(result.get("ContentType", "application/octet-stream")),
            "etag": str(result.get("ETag", "")).strip('"'),
            "bytes": len(body),
        }

    def set_tenant_access(self, tenant: dict, *, enabled: bool) -> None:
        tenant_id = self._tenant_id(tenant)
        vhost = str(tenant.get("rabbitmq_vhost", "")).strip()
        username = "air-" + tenant_id.replace("-", "")[:24]
        encoded_vhost, encoded_user = quote(vhost, safe=""), quote(username, safe="")
        if enabled:
            self.provision(tenant)
            return
        try:
            response = self.http.delete(f"/api/permissions/{encoded_vhost}/{encoded_user}")
            if response.status_code not in {200, 204, 404}:
                raise TenantInfrastructureError(
                    f"RabbitMQ permission revocation returned HTTP {response.status_code}"
                )
        except httpx.HTTPError as exc:
            raise TenantInfrastructureError("Could not suspend tenant RabbitMQ access") from exc

    def close(self) -> None:
        self.http.close()
