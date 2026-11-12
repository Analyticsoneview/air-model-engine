#!/usr/bin/env python3
"""Create missing local AIR secrets without replacing existing credentials."""
from __future__ import annotations

import base64
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".air-secrets")
root.mkdir(parents=True, exist_ok=True)


def ensure(name: str, factory) -> str:
    path = root / name
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise SystemExit(f"Existing secret is empty: {path}")
        return value
    value = factory()
    path.write_text(value, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print(f"Created {name}")
    return value


jwt = ensure("jwt_secret", lambda: secrets.token_urlsafe(48))
credential = ensure("credential_key", lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
admin_api = ensure("admin_api_key", lambda: secrets.token_urlsafe(48))
admin_mfa = ensure("admin_mfa_key", lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
pg_password = ensure("postgres_password", lambda: secrets.token_hex(32))
redis_password = ensure("redis_password", lambda: secrets.token_hex(32))
ensure("database_url", lambda: f"postgresql+psycopg://air:{quote(pg_password, safe='')}@postgres:5432/air")
ensure("redis_url", lambda: f"redis://:{quote(redis_password, safe='')}@redis:6379/0")
print("AIR local secrets are ready; existing values were preserved.")
