import pytest

from app.persistence import PersistenceRuntime


def test_persistence_runtime_keeps_postgres_and_redis_optional(monkeypatch):
    monkeypatch.delenv("AIR_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIR_DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("AIR_REDIS_URL", raising=False)
    monkeypatch.delenv("AIR_REDIS_URL_FILE", raising=False)
    runtime = PersistenceRuntime()
    try:
        assert runtime.health() == {
            "postgresql": {"configured": False, "status": "disabled"},
            "redis": {"configured": False, "status": "disabled"},
        }
    finally:
        runtime.close()


def test_persistence_runtime_rejects_non_postgres_database_url(monkeypatch):
    monkeypatch.setenv("AIR_DATABASE_URL", "sqlite:///./air.db")
    monkeypatch.delenv("AIR_DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("AIR_REDIS_URL", raising=False)
    monkeypatch.delenv("AIR_REDIS_URL_FILE", raising=False)
    with pytest.raises(RuntimeError, match="must use PostgreSQL"):
        PersistenceRuntime()
