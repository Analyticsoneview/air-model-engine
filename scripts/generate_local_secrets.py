#!/usr/bin/env python3
"""Create missing local AIR Compose secrets without rotating existing keys."""
from pathlib import Path
import base64
import secrets

ROOT = Path("/secrets")
ROOT.mkdir(parents=True, exist_ok=True)

def read(name):
    path = ROOT / name
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

def write(name, value):
    path = ROOT / name
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        path.write_text(value, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

jwt = read("jwt_secret") or secrets.token_urlsafe(48)
credential = read("credential_key") or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
admin_api = read("admin_api_key") or secrets.token_urlsafe(48)
# Fernet keys are URL-safe base64 encodings of exactly 32 random bytes.
mfa = read("admin_mfa_key") or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
pg = read("postgres_password") or secrets.token_urlsafe(32)
redis = read("redis_password") or secrets.token_urlsafe(32)

values = {
    "jwt_secret": jwt,
    "credential_key": credential,
    "admin_api_key": admin_api,
    "admin_mfa_key": mfa,
    "postgres_password": pg,
    "redis_password": redis,
    "database_url": read("database_url") or f"postgresql+psycopg://air:{pg}@postgres:5432/air",
    "redis_url": read("redis_url") or f"redis://:{redis}@redis:6379/0",
}
for name, value in values.items():
    write(name, value)
missing = [name for name in values if not (ROOT / name).is_file() or not read(name)]
if missing:
    raise SystemExit("Failed to create required AIR secrets: " + ", ".join(missing))
print("All 8 required AIR local secrets are present; existing non-empty secrets were preserved.")
