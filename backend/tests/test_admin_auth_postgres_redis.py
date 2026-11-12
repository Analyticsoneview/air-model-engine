from app.admin_auth_postgres import PostgresAdminAuthStore


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)


def test_successful_login_clears_redis_failure_counter_and_lock():
    store = PostgresAdminAuthStore.__new__(PostgresAdminAuthStore)
    store.redis = MemoryRedis()
    key = "hashed-rate-key"
    failure_key = "air:admin:fail:" + key
    lock_key = "air:admin:lock:" + key
    store.redis.setex(failure_key, 900, "4")
    store.redis.setex(lock_key, 900, "1")
    store._clear_login_limit(key)
    assert failure_key not in store.redis.values
    assert lock_key not in store.redis.values


def test_successful_login_reset_prevents_old_failures_carrying_forward():
    store = PostgresAdminAuthStore.__new__(PostgresAdminAuthStore)
    store.redis = MemoryRedis()
    key = "hashed-rate-key"
    failure_key = "air:admin:fail:" + key
    store.redis.setex(failure_key, 900, "4")
    store._clear_login_limit(key)
    store.redis.setex(failure_key, 900, "1")
    assert store.redis.values[failure_key] == "1"
