"""Alembic environment for AIR PostgreSQL migrations."""
from __future__ import annotations

import os
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    for name in ("AIR_CUSTOMER_DATABASE_URL", "AIR_DATABASE_URL"):
        secret_file = os.getenv(name + "_FILE")
        value = Path(secret_file).read_text(encoding="utf-8").strip() if secret_file else os.getenv(name, "")
        if value:
            if not value.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError(f"{name} must use PostgreSQL")
            return value
    raise RuntimeError("AIR_CUSTOMER_DATABASE_URL or AIR_DATABASE_URL (or corresponding _FILE) is required to run migrations")


config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
