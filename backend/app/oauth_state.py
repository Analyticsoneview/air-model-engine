"""Shared, expiring one-time OAuth state storage.

Redis is authoritative when AIR_REDIS_URL is configured. If Redis is not
configured, a process-local fallback preserves single-worker development
compatibility. A configured but unavailable Redis instance fails closed.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from redis import Redis
from redis.exceptions import RedisError

_STATE_TTL_SECONDS = 600
_COMPARE_AND_DELETE = """
local value = redis.call('GET', KEYS[1])
if value and value == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def _setting(name: str) -> str:
    file_name = os.getenv(name + "_FILE")
    return Path(file_name).read_text(encoding="utf-8").strip() if file_name else os.getenv(name, "").strip()


class OAuthStateStore:
    def __init__(self, redis_url: str | None = None, redis_client=None):
        configured_url = redis_url if redis_url is not None else _setting("AIR_REDIS_URL")
        self.redis = redis_client if redis_client is not None else (
            Redis.from_url(configured_url, decode_responses=True, socket_connect_timeout=3,
                           socket_timeout=3, health_check_interval=30)
            if configured_url else None
        )
        self._local: dict[str, str] = {}

    @staticmethod
    def _key(provider: str, customer_id: str, account_id: str) -> str:
        identity = "\\0".join((provider.strip().lower(), customer_id, account_id)).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()
        return "air:oauth:state:" + digest

    def issue(self, provider: str, customer_id: str, account_id: str, state: str,
              ttl_seconds: int = _STATE_TTL_SECONDS) -> None:
        if not 1 <= ttl_seconds <= 900:
            raise ValueError("OAuth state TTL must be between 1 and 900 seconds")
        key = self._key(provider, customer_id, account_id)
        if self.redis is None:
            self._local[key] = state
            return
        try:
            self.redis.set(key, state, ex=ttl_seconds)
        except RedisError as exc:
            raise RuntimeError("Shared OAuth state storage is unavailable") from exc

    def consume(self, provider: str, customer_id: str, account_id: str, supplied_state: str) -> bool:
        key = self._key(provider, customer_id, account_id)
        if self.redis is None:
            expected = self._local.get(key)
            if expected is None or not hmac.compare_digest(expected, supplied_state):
                return False
            del self._local[key]
            return True
        try:
            # Compare and delete atomically: an invalid attempt cannot burn a valid state.
            return bool(self.redis.eval(_COMPARE_AND_DELETE, 1, key, supplied_state))
        except RedisError as exc:
            raise RuntimeError("Shared OAuth state storage is unavailable") from exc

    def close(self) -> None:
        if self.redis is not None:
            self.redis.close()


_oauth_state_store: OAuthStateStore | None = None


def get_oauth_state_store() -> OAuthStateStore:
    global _oauth_state_store
    if _oauth_state_store is None:
        _oauth_state_store = OAuthStateStore()
    return _oauth_state_store
