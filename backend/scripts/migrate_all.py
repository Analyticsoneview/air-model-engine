"""Apply PostgreSQL migrations and reconcile legacy SQLite repositories before API startup."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.db_compat import read_database_url
from app.scripts.migrate_admin_sqlite_to_postgres import migrate as migrate_admin
from app.scripts.migrate_customer_auth_sqlite_to_postgres import migrate as migrate_customer_auth
from scripts.import_sqlite_domain_stores import run as migrate_domain_stores


def main() -> None:
    database_url = read_database_url("AIR_DATABASE_URL")
    if not database_url:
        raise RuntimeError("AIR_DATABASE_URL or AIR_DATABASE_URL_FILE is required before API startup")

    os.environ.setdefault("AIR_CUSTOMER_DATABASE_URL", database_url)
    os.environ.setdefault("AIR_ADMIN_DATABASE_URL", database_url)

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    customer_source = os.getenv("AIR_CUSTOMER_SQLITE_PATH", os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3"))
    admin_source = os.getenv("AIR_ADMIN_SQLITE_PATH", os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3"))

    customer_result = migrate_customer_auth(customer_source, os.environ["AIR_CUSTOMER_DATABASE_URL"])
    admin_result = migrate_admin(admin_source, os.environ["AIR_ADMIN_DATABASE_URL"])
    domain_result = migrate_domain_stores(Path("data"), dry_run=False)

    report = {
        "alembic": "UPGRADED",
        "customer_auth": customer_result,
        "admin_auth": admin_result,
        "domain_stores": domain_result,
    }
    print(json.dumps(report, indent=2, default=str))

    allowed = {"IMPORTED_AND_RECONCILED", "ALREADY_IMPORTED", "NO_SOURCE_FILE"}
    for name, result in (
        ("customer_auth", customer_result),
        ("admin_auth", admin_result),
        ("domain_stores", domain_result),
    ):
        if result.get("status") not in allowed:
            raise RuntimeError(f"{name} migration did not complete safely: {result}")


if __name__ == "__main__":
    main()
