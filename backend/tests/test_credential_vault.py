import sqlite3
from cryptography.fernet import Fernet

from app.credential_vault import CredentialVault


def test_default_vault_uses_configured_sqlite_path_when_postgres_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("AIR_CREDENTIAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIR_CREDENTIAL_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("AIR_CREDENTIAL_KEY", Fernet.generate_key().decode())
    db_path = tmp_path / "configured-credentials.sqlite3"
    monkeypatch.setenv("AIR_CREDENTIAL_DB_PATH", str(db_path))

    vault = CredentialVault()
    try:
        vault.put("customer-1", "zerodha", "account-1", {"api_key": "test-key"})
        assert vault.get("customer-1", "zerodha", "account-1") == {"api_key": "test-key"}
    finally:
        vault.close()

    assert db_path.is_file()
