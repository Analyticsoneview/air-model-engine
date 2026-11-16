from __future__ import annotations

import hashlib
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security import require_customer
from app.tenant_context import tenant_scope
import app.tenant_storage_api as storage_api


TENANT_ID = "11111111-2222-4333-8444-555555555555"
CUSTOMER_ID = "+919876543210"


class FakeRegistry:
    def __init__(self, limit=10):
        self.limit = limit
        self.used = 0
        self.objects = {}

    def get_customer_context(self, customer_id):
        assert customer_id == CUSTOMER_ID
        return {
            "tenant_id": TENANT_ID, "status": "ACTIVE", "tenant_status": "ACTIVE",
            "role": "OWNER", "max_storage_bytes": self.limit, "storage_used_bytes": self.used,
        }

    def reserve_object_upload(self, tenant_id, customer_id, object_key, *, size_bytes, sha256, content_type):
        assert tenant_id == TENANT_ID and customer_id == CUSTOMER_ID
        if object_key.startswith("/") or ".." in object_key.split("/"):
            raise ValueError("unsafe key")
        existing = self.objects.get(object_key)
        if existing:
            if (
                existing["size_bytes"] != size_bytes
                or existing["sha256"] != sha256
                or existing["content_type"] != content_type
            ):
                raise FileExistsError("immutable key")
            return {
                "already_stored": existing["status"] == "STORED",
                "resume_pending": existing["status"] == "PENDING",
                **existing, "storage_used_bytes": self.used, "max_storage_bytes": self.limit,
            }
        if self.used + size_bytes > self.limit:
            raise OverflowError("quota")
        self.used += size_bytes
        self.objects[object_key] = {
            "size_bytes": size_bytes, "sha256": sha256, "content_type": content_type,
            "status": "PENDING",
        }
        return {
            "already_stored": False, "resume_pending": False, "storage_used_bytes": self.used,
            "max_storage_bytes": self.limit,
        }

    def complete_object_upload(self, tenant_id, customer_id, object_key, etag):
        value = self.objects[object_key]
        value.update(status="STORED", etag=etag, object_key=object_key)
        return dict(value)

    def list_tenant_objects(self, tenant_id, customer_id, *, limit=100, offset=0):
        values = [
            {"object_key": key, **value}
            for key, value in self.objects.items() if value["status"] == "STORED"
        ]
        return values[offset:offset + limit]

    def get_tenant_object(self, tenant_id, customer_id, object_key):
        value = self.objects.get(object_key)
        if not value or value["status"] != "STORED":
            raise KeyError(object_key)
        return {"object_key": object_key, **value}


class FakeProvisioner:
    def __init__(self):
        self.objects = {}
        self.put_calls = 0
        self.fail_once = False

    def put_tenant_object(self, tenant, key, body, *, content_type, sha256, quota_prevalidated):
        self.put_calls += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated ambiguous S3 failure")
        self.objects[key] = (body, content_type, sha256)
        return {"etag": "etag-123"}

    def get_tenant_object(self, tenant, key):
        body, content_type, _ = self.objects[key]
        return {"body": body, "content_type": content_type, "etag": "etag-123"}


def _client(monkeypatch, *, limit=10):
    monkeypatch.setenv("AIR_DEPLOYMENT_PROFILE", "aws-saas-multi")
    registry, provisioner = FakeRegistry(limit), FakeProvisioner()
    app = FastAPI()
    app.include_router(storage_api.router)

    async def customer_dependency():
        with tenant_scope(tenant_id=TENANT_ID, customer_id=CUSTOMER_ID):
            yield CUSTOMER_ID

    app.dependency_overrides[require_customer] = customer_dependency
    monkeypatch.setattr(storage_api, "_services", lambda: (registry, lambda: provisioner))
    return TestClient(app), registry, provisioner


def test_upload_list_download_and_idempotent_retry(monkeypatch):
    client, registry, provisioner = _client(monkeypatch, limit=100)
    response = client.put(
        "/api/v1/tenant/objects/reports/daily.csv",
        content=b"alpha", headers={"content-type": "text/csv"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "stored"
    assert registry.used == 5
    assert provisioner.put_calls == 1

    retry = client.put(
        "/api/v1/tenant/objects/reports/daily.csv",
        content=b"alpha", headers={"content-type": "text/csv"},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "already_stored"
    assert provisioner.put_calls == 1
    assert registry.used == 5

    listing = client.get("/api/v1/tenant/objects")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["storage_used_bytes"] == 5

    downloaded = client.get("/api/v1/tenant/objects/reports/daily.csv")
    assert downloaded.status_code == 200
    assert downloaded.content == b"alpha"
    assert downloaded.headers["x-air-content-sha256"] == hashlib.sha256(b"alpha").hexdigest()


def test_upload_enforces_quota_immutable_keys_and_size_limit(monkeypatch):
    client, registry, provisioner = _client(monkeypatch, limit=5)
    first = client.put("/api/v1/tenant/objects/a.bin", content=b"12345")
    assert first.status_code == 200
    too_large_for_quota = client.put("/api/v1/tenant/objects/b.bin", content=b"x")
    assert too_large_for_quota.status_code == 409
    changed_content = client.put("/api/v1/tenant/objects/a.bin", content=b"other")
    assert changed_content.status_code == 409
    assert registry.used == 5
    assert provisioner.put_calls == 1

    with patch.dict("os.environ", {"AIR_TENANT_MAX_UPLOAD_BYTES": "4"}):
        over_request_limit = client.put("/api/v1/tenant/objects/c.bin", content=b"12345")
    assert over_request_limit.status_code == 413


def test_pending_upload_resumes_after_ambiguous_s3_failure(monkeypatch):
    client, registry, provisioner = _client(monkeypatch, limit=100)
    provisioner.fail_once = True
    first = client.put("/api/v1/tenant/objects/reports/resume.csv", content=b"resume")
    assert first.status_code == 502
    assert registry.used == 6
    assert registry.objects["reports/resume.csv"]["status"] == "PENDING"

    retry = client.put("/api/v1/tenant/objects/reports/resume.csv", content=b"resume")
    assert retry.status_code == 200
    assert retry.json()["status"] == "stored"
    assert retry.json()["resumed"] is True
    assert registry.used == 6
    assert registry.objects["reports/resume.csv"]["status"] == "STORED"


def test_registry_membership_must_match_verified_request_tenant(monkeypatch):
    client, registry, _ = _client(monkeypatch)
    registry.get_customer_context = lambda customer_id: {
        "tenant_id": "99999999-2222-4333-8444-555555555555",
        "tenant_status": "ACTIVE", "max_storage_bytes": 10, "storage_used_bytes": 0,
    }
    response = client.get("/api/v1/tenant/objects")
    assert response.status_code == 403


def test_read_only_tenant_member_can_read_but_cannot_upload(monkeypatch):
    client, registry, provisioner = _client(monkeypatch, limit=100)
    registry.get_customer_context = lambda customer_id: {
        "tenant_id": TENANT_ID, "tenant_status": "ACTIVE", "role": "READ_ONLY",
        "max_storage_bytes": 100, "storage_used_bytes": 0,
    }
    response = client.put("/api/v1/tenant/objects/blocked.bin", content=b"x")
    assert response.status_code == 403
    assert registry.used == 0
    assert provisioner.put_calls == 0


def test_storage_api_is_disabled_outside_aws_saas(monkeypatch):
    client, _, _ = _client(monkeypatch)
    with patch.dict("os.environ", {"AIR_DEPLOYMENT_PROFILE": "onprem-single"}):
        response = client.get("/api/v1/tenant/objects")
    assert response.status_code == 409


def test_invalid_object_key_and_missing_download_are_rejected(monkeypatch):
    client, _, _ = _client(monkeypatch)
    unsafe = client.put("/api/v1/tenant/objects/%2E%2E/escape.bin", content=b"x")
    assert unsafe.status_code in {400, 404, 422}
    missing = client.get("/api/v1/tenant/objects/missing.bin")
    assert missing.status_code == 404
