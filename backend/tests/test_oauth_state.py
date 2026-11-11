import os
import time
import unittest
import uuid

import pytest

from redis.exceptions import RedisError

from app.oauth_state import OAuthStateStore


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def eval(self, script, key_count, key, supplied):
        if self.values.get(key) == supplied:
            del self.values[key]
            self.ttls.pop(key, None)
            return 1
        return 0

    def close(self):
        pass


class BrokenRedis:
    def set(self, *args, **kwargs):
        raise RedisError("offline")

    def eval(self, *args, **kwargs):
        raise RedisError("offline")


class OAuthStateStoreTests(unittest.TestCase):
    def test_local_state_is_single_use_and_invalid_attempt_does_not_consume(self):
        store = OAuthStateStore(redis_url="")
        store.issue("upstox", "customer-1", "account-1", "high-entropy-state")
        self.assertFalse(store.consume("upstox", "customer-1", "account-1", "wrong-state"))
        self.assertTrue(store.consume("upstox", "customer-1", "account-1", "high-entropy-state"))
        self.assertFalse(store.consume("upstox", "customer-1", "account-1", "high-entropy-state"))

    def test_redis_state_is_shared_and_single_use(self):
        redis = FakeRedis()
        store_a = OAuthStateStore(redis_client=redis)
        store_b = OAuthStateStore(redis_client=redis)
        store_a.issue("fyers", "customer-2", "account-9", "state-value", ttl_seconds=300)
        key = next(iter(redis.values))
        self.assertTrue(key.startswith("air:oauth:state:"))
        self.assertNotIn("customer-2", key)
        self.assertEqual(redis.ttls[key], 300)
        self.assertFalse(store_b.consume("fyers", "customer-2", "account-9", "invalid"))
        self.assertTrue(store_b.consume("fyers", "customer-2", "account-9", "state-value"))
        self.assertFalse(store_a.consume("fyers", "customer-2", "account-9", "state-value"))

    def test_redis_unavailable_fails_closed(self):
        store = OAuthStateStore(redis_client=BrokenRedis())
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            store.issue("upstox", "customer-3", "account-1", "state-value")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            store.consume("upstox", "customer-3", "account-1", "state-value")

    def test_invalid_ttl_is_rejected(self):
        store = OAuthStateStore(redis_url="")
        with self.assertRaises(ValueError):
            store.issue("upstox", "customer-1", "account-1", "state", ttl_seconds=0)


def test_real_redis_state_is_shared_atomic_and_expires():
    redis_url = os.getenv("AIR_TEST_REDIS_URL", "").strip()
    if not redis_url:
        pytest.skip("AIR_TEST_REDIS_URL not configured; real Redis integration runs in CI")
    store_a = OAuthStateStore(redis_url=redis_url)
    store_b = OAuthStateStore(redis_url=redis_url)
    customer_id = "redis-test-" + uuid.uuid4().hex
    account_id = "account-" + uuid.uuid4().hex
    try:
        store_a.issue("upstox", customer_id, account_id, "correct-state", ttl_seconds=30)
        assert not store_b.consume("upstox", customer_id, account_id, "wrong-state")
        assert store_b.consume("upstox", customer_id, account_id, "correct-state")
        assert not store_a.consume("upstox", customer_id, account_id, "correct-state")

        store_a.issue("fyers", customer_id, account_id, "expires-state", ttl_seconds=1)
        time.sleep(1.2)
        assert not store_b.consume("fyers", customer_id, account_id, "expires-state")
    finally:
        store_a.close()
        store_b.close()


if __name__ == "__main__":
    unittest.main()
