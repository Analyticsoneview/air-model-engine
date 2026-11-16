from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.tenant_quotas import TenantApiQuotaEnforcer, TenantApiQuotaExceeded


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

    def test_invalid_tenant_or_limit_is_rejected(self):
        quota = TenantApiQuotaEnforcer(FakeRedis())
        with self.assertRaises(ValueError):
            quota.consume("", 10)
        with self.assertRaises(ValueError):
            quota.consume("tenant-a", 0)


if __name__ == "__main__":
    unittest.main()
