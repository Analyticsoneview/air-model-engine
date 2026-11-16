"""Per-tenant API quota enforcement for AIR AWS SaaS."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


class TenantApiQuotaExceeded(RuntimeError):
    """Raised when a tenant has consumed its daily API allowance."""


class TenantApiQuotaEnforcer:
    def __init__(self, redis_client):
        self.redis = redis_client

    @classmethod
    def from_environment(cls) -> "TenantApiQuotaEnforcer":
        file_path = os.getenv("AIR_REDIS_URL_FILE", "").strip()
        redis_url = Path(file_path).read_text(encoding="utf-8").strip() if file_path else os.getenv("AIR_REDIS_URL", "").strip()
        if not redis_url:
            raise RuntimeError("AIR_REDIS_URL or AIR_REDIS_URL_FILE is required for SaaS quota enforcement")
        import redis
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
        client.ping()
        return cls(client)

    def consume(self, tenant_id: str, daily_limit: int, *, now: datetime | None = None) -> int:
        tenant = str(tenant_id or "").strip()
        limit = int(daily_limit)
        if not tenant or limit < 1:
            raise ValueError("A tenant ID and positive API quota are required")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        day = current.astimezone(timezone.utc).strftime("%Y%m%d")
        key = f"air:tenant:{tenant}:api:{day}"
        pipeline = self.redis.pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, 172800)
        result = pipeline.execute()
        count = int(result[0])
        if count > limit:
            raise TenantApiQuotaExceeded("Tenant daily API quota has been exceeded")
        return count

    def close(self) -> None:
        close = getattr(self.redis, "close", None)
        if callable(close):
            close()
