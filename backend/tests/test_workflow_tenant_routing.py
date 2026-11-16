from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from app.tenant_context import tenant_scope
from app.workflow_engine import WorkflowStore
from app.workflow_worker import _TENANT_RABBITMQ_URLS, _tenant_rabbit_url


class WorkflowTenantRoutingTests(unittest.TestCase):
    def tearDown(self):
        _TENANT_RABBITMQ_URLS.clear()

    def test_outbox_rows_retain_tenant_identity_for_vhost_routing(self):
        store = WorkflowStore(db_path=":memory:")
        try:
            with tenant_scope(tenant_id="tenant-a", customer_id="+919876543210"):
                store.create_workflow(
                    name="Tenant A workflow", created_by="customer-admin",
                    trigger_type="EVENT", trigger_config={"event_type": "tenant.a"},
                )
                store.publish_event(
                    event_type="tenant.a", source="test", payload={"symbol": "NIFTY"},
                    idempotency_key="tenant-a-routing-1",
                )
            with tenant_scope(is_admin=True):
                pending = store.pending_outbox(10)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["tenant_id"], "tenant-a")
            self.assertEqual(pending[0]["customer_id"], "+919876543210")
        finally:
            store.close()

    def test_tenant_rabbitmq_url_uses_per_tenant_secret_and_vhost(self):
        tenant_id = "11111111-2222-4333-8444-555555555555"
        tenant = {
            "tenant_id": tenant_id,
            "status": "ACTIVE",
            "rabbitmq_vhost": "air-tenant-a",
            "metadata_json": {
                "aws_provisioning": {
                    "status": "PROVISIONED",
                    "credentials_secret_arn": "arn:aws:secretsmanager:ap-south-1:123456789012:secret:air/tenants/a",
                }
            },
        }
        secret_payload = {
            "rabbitmq_username": "tenant/user",
            "rabbitmq_password": "p@ss/word",
            "credential_key": "not-used-by-transport",
        }
        with patch.dict(os.environ, {
            "AIR_RABBITMQ_URL": "amqps://air:admin-password@mq.example.test:5671/",
            "AWS_REGION": "ap-south-1",
        }, clear=False):
            with patch("app.tenant_provisioning.TenantRegistry") as registry_class:
                registry = registry_class.return_value
                registry.get_tenant.return_value = tenant
                with patch("boto3.client") as boto_client:
                    boto_client.return_value.get_secret_value.return_value = {
                        "SecretString": json.dumps(secret_payload)
                    }
                    url = _tenant_rabbit_url(tenant_id)
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "amqps")
        self.assertEqual(parsed.hostname, "mq.example.test")
        self.assertEqual(parsed.port, 5671)
        self.assertEqual(parsed.username, "tenant%2Fuser")
        self.assertEqual(parsed.password, "p%40ss%2Fword")
        self.assertEqual(parsed.path, "/air-tenant-a")
        registry.close.assert_called_once()
        boto_client.assert_called_once_with("secretsmanager", region_name="ap-south-1")

    def test_suspended_or_unprovisioned_tenants_cannot_open_vhost_connections(self):
        tenant_id = "11111111-2222-4333-8444-555555555555"
        tenant = {"tenant_id": tenant_id, "status": "SUSPENDED", "metadata_json": {}}
        with patch("app.tenant_provisioning.TenantRegistry") as registry_class:
            registry_class.return_value.get_tenant.return_value = tenant
            with self.assertRaisesRegex(RuntimeError, "not ACTIVE"):
                _tenant_rabbit_url(tenant_id)


if __name__ == "__main__":
    unittest.main()
