"""Optional PostgreSQL and Redis connectivity foundation.

SQLite-backed repositories remain the compatibility/local-mode implementation.
This module centralizes connection lifecycle and health checks while repositories
are migrated incrementally; it does not silently move or discard SQLite data.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from redis import Redis


def _read_setting(name: str, default: str = "") -> str:
    file_name = os.getenv(f"{name}_FILE")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return os.getenv(name, default).strip()


class PersistenceRuntime:
    def __init__(self) -> None:
        self.database_url = _read_setting("AIR_DATABASE_URL")
        self.redis_url = _read_setting("AIR_REDIS_URL")
        self.engine: Engine | None = None
        self.redis: Redis | None = None
        if self.database_url:
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("AIR_DATABASE_URL must use PostgreSQL")
            self.engine = create_engine(
                self.database_url,
                pool_pre_ping=True,
                pool_size=int(os.getenv("AIR_DB_POOL_SIZE", "5")),
                max_overflow=int(os.getenv("AIR_DB_MAX_OVERFLOW", "10")),
                pool_recycle=1800,
                future=True,
            )
        if self.redis_url:
            self.redis = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
            )

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "postgresql": {"configured": self.engine is not None, "status": "disabled"},
            "redis": {"configured": self.redis is not None, "status": "disabled"},
        }
        if self.engine is not None:
            try:
                with self.engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                result["postgresql"]["status"] = "ok"
            except Exception as exc:
                result["postgresql"].update(status="error", error=type(exc).__name__)
        if self.redis is not None:
            try:
                self.redis.ping()
                result["redis"]["status"] = "ok"
            except Exception as exc:
                result["redis"].update(status="error", error=type(exc).__name__)
        return result

    def close(self) -> None:
        if self.redis is not None:
            self.redis.close()
        if self.engine is not None:
            self.engine.dispose()


_runtime: PersistenceRuntime | None = None


def get_persistence_runtime() -> PersistenceRuntime:
    global _runtime
    if _runtime is None:
        _runtime = PersistenceRuntime()
    return _runtime
