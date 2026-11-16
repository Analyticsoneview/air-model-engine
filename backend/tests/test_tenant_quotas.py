from __future__ import annotations

import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from app.tenant_quotas import TenantApiQuotaEnforcer, TenantApiQuotaExceeded
from fastapi import HTTPException
from app import security


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.key = None

    def incr(self, key):
        self.key = key
        return self

    def expire(self, key, seconds):
        self.redis.expiries[key] = seconds
        return self

    def execute(self):
        self.redis.counts[self.key] = self.redis.counts.get(self.key, 0) + 1
        return [self.redis.counts[self.key], True]


class FakeRedis:
    def __init__(self):
        self.counts = {}
        self.expiries = {}

    def pipeline(self, transaction=True):
        return FakePipeline(self)


class TenantApiQuotaTests(unittest.TestCase):
    def test_daily_quota_increments_tenant_scoped_redis_key(self):
        redis = FakeRedis()
        quota = TenantApiQuotaEnforcer(redis)
        now = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(quota.consume("tenant-a", 2, now=now), 1)
        self.assertEqual(quota.consume("tenant-a", 2, now=now), 2)
        key = "air:tenant:tenant-a:api:20261116"
        self.assertEqual(redis.counts[key], 2)
        self.assertEqual(redis.expiries[key], 172800)

    def test_quota_isolated_between_tenants_and_utc_days(self):
        redis = FakeRedis()
        quota = TenantApiQuotaEnforcer(redis)
        day_one = datetime(2026, 11, 16, 23, 59, tzinfo=timezone.utc)
        day_two = datetime(2026, 11, 17, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(quota.consume("tenant-a", 1, now=day_one), 1)
        self.assertEqual(quota.consume("tenant-b", 1, now=day_one), 1)
        self.assertEqual(quota.consume("tenant-a", 1, now=day_two), 1)

    def test_daily_limit_fails_closed_after_limit_is_reached(self):
        quota = TenantApiQuotaEnforcer(FakeRedis())
        now = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
        quota.consume("tenant-a", 1, now=now)
        with self.assertRaises(TenantApiQuotaExceeded):
            quota.consume("tenant-a", 1, now=now)

    def test_customer_auth_rejects_requests_after_saas_daily_limit(self):
        class Registry:
            def get_tenant(self, tenant_id):
                return {"status": "ACTIVE", "max_api_calls_per_day": 1}

        class Enforcer:
            def consume(self, tenant_id, daily_limit):
                raise TenantApiQuotaExceeded("limit reached")

        original_registry = security._tenant_quota_registry
        original_enforcer = security._tenant_api_quota_enforcer
        security._tenant_quota_registry = Registry()
        security._tenant_api_quota_enforcer = Enforcer()
        try:
            with patch.dict("os.environ", {"AIR_DEPLOYMENT_PROFILE": "aws-saas-multi"}, clear=False):
                with self.assertRaises(HTTPException) as raised:
                    security._consume_tenant_api_quota("tenant-a")
            self.assertEqual(raised.exception.status_code, 429)
        finally:
            security._tenant_quota_registry = original_registry
            security._tenant_api_quota_enforcer = original_enforcer

    def test_invalid_tenant_or_limit_is_rejected(self):
        quota = TenantApiQuotaEnforcer(FakeRedis())
        with self.assertRaises(ValueError):
            quota.consume("", 10)
        with self.assertRaises(ValueError):
            quota.consume("tenant-a", 0)


if __name__ == "__main__":
    unittest.main()
