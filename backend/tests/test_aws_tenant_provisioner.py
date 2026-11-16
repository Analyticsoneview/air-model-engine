from __future__ import annotations

import json
import unittest

import httpx

from app.aws_tenant_provisioner import AwsTenantProvisioner, TenantInfrastructureError


class FakeClientError(Exception):
    def __init__(self, code: str):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": 404}}
        super().__init__(code)


class FakeS3:
    def __init__(self):
        self.buckets = set()
        self.calls = []

    def head_bucket(self, **kwargs):
        self.calls.append(("head_bucket", kwargs))
        if kwargs["Bucket"] not in self.buckets:
            raise FakeClientError("404")

    def create_bucket(self, **kwargs):
        self.calls.append(("create_bucket", kwargs))
        self.buckets.add(kwargs["Bucket"])

    def put_public_access_block(self, **kwargs):
        self.calls.append(("public_access", kwargs))

    def put_bucket_encryption(self, **kwargs):
        self.calls.append(("encryption", kwargs))

    def put_bucket_versioning(self, **kwargs):
        self.calls.append(("versioning", kwargs))

    def put_bucket_tagging(self, **kwargs):
        self.calls.append(("tagging", kwargs))


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def describe_secret(self, SecretId):
        if SecretId not in self.values:
            raise FakeClientError("ResourceNotFoundException")
        return {"ARN": "arn:aws:secretsmanager:ap-south-1:123456789012:secret:" + SecretId}

    def get_secret_value(self, SecretId):
        return {"SecretString": self.values[SecretId]}

    def create_secret(self, Name, **kwargs):
        self.values[Name] = kwargs["SecretString"]
        return {"ARN": "arn:aws:secretsmanager:ap-south-1:123456789012:secret:" + Name}

    def put_secret_value(self, SecretId, SecretString):
        self.values[SecretId] = SecretString


class AwsTenantProvisionerTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.secrets = FakeSecrets()
        self.requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(204, request=request)

        self.http = httpx.Client(
            base_url="https://rabbitmq.example.test:15671",
            transport=httpx.MockTransport(handler),
        )
        self.provisioner = AwsTenantProvisioner(
            s3_client=self.s3,
            secrets_client=self.secrets,
            http_client=self.http,
            bucket_prefix="air-tenant-",
            secrets_prefix="air/tenants",
            rabbitmq_admin_user="air",
            region="ap-south-1",
        )
        self.tenant = {
            "tenant_id": "11111111-2222-4333-8444-555555555555",
            "name": "Tenant One",
            "plan_code": "PAID",
            "status": "PROVISIONING",
            "storage_prefix": "tenants/11111111-2222-4333-8444-555555555555/",
            "rabbitmq_vhost": "air-11111111222243338444555555555555",
            "max_members": 5,
            "max_api_calls_per_day": 100000,
            "max_storage_bytes": 10737418240,
        }

    def tearDown(self):
        self.provisioner.close()

    def test_provision_creates_private_encrypted_versioned_bucket_vhost_and_secret(self):
        result = self.provisioner.provision(self.tenant)
        bucket = result["storage"]["bucket"]
        self.assertEqual(result["status"], "PROVISIONED")
        self.assertIn(bucket, self.s3.buckets)
        self.assertTrue(any(call[0] == "public_access" for call in self.s3.calls))
        encryption = next(call[1] for call in self.s3.calls if call[0] == "encryption")
        self.assertEqual(
            encryption["ServerSideEncryptionConfiguration"]["Rules"][0]
            ["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"],
            "AES256",
        )
        versioning = next(call[1] for call in self.s3.calls if call[0] == "versioning")
        self.assertEqual(versioning["VersioningConfiguration"]["Status"], "Enabled")
        methods = [request.method for request in self.requests]
        self.assertEqual(methods, ["PUT", "PUT", "PUT"])
        self.assertIn("/api/vhosts/", self.requests[0].url.path)
        self.assertIn("/api/users/", self.requests[1].url.path)
        self.assertIn("/api/permissions/", self.requests[2].url.path)
        secret_payload = json.loads(next(iter(self.secrets.values.values())))
        self.assertEqual(secret_payload["tenant_id"], self.tenant["tenant_id"])
        self.assertTrue(secret_payload["rabbitmq_password"])
        self.assertTrue(secret_payload["credential_key"])
        self.assertEqual(result["quotas"]["max_members"], 5)

    def test_repeated_provision_is_idempotent_and_reuses_tenant_credentials(self):
        first = self.provisioner.provision(self.tenant)
        secret_before = dict(self.secrets.values)
        self.requests.clear()
        second = self.provisioner.provision(self.tenant)
        self.assertEqual(first["storage"], second["storage"])
        self.assertEqual(first["credentials_secret_arn"], second["credentials_secret_arn"])
        self.assertEqual(secret_before, self.secrets.values)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len(self.s3.buckets), 1)

    def test_suspend_revokes_tenant_user_permissions_without_deleting_data(self):
        self.provisioner.provision(self.tenant)
        self.requests.clear()
        self.provisioner.set_tenant_access(self.tenant, enabled=False)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].method, "DELETE")
        self.assertIn("/api/permissions/", self.requests[0].url.path)
        self.assertEqual(len(self.s3.buckets), 1)
        self.assertEqual(len(self.secrets.values), 1)

    def test_invalid_tenant_id_and_bucket_prefix_fail_closed(self):
        bad = dict(self.tenant, tenant_id="not-a-uuid")
        with self.assertRaises(ValueError):
            self.provisioner.provision(bad)
        with self.assertRaises(ValueError):
            AwsTenantProvisioner(
                s3_client=self.s3, secrets_client=self.secrets, http_client=self.http,
                bucket_prefix="InvalidPrefix-", secrets_prefix="air/tenants",
                rabbitmq_admin_user="air", region="ap-south-1",
            )


if __name__ == "__main__":
    unittest.main()
