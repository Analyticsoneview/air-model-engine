"""Integration tests for the Admin SQLite-to-PostgreSQL transfer.

Set AIR_TEST_ADMIN_DATABASE_URL to a disposable PostgreSQL database whose
migrations have been applied. Test rows and the import marker are isolated
from other PostgreSQL integration tests.
"""
import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from app.scripts.migrate_admin_sqlite_to_postgres import migrate


@pytest.fixture
def postgres_url():
    value = os.getenv("AIR_TEST_ADMIN_DATABASE_URL")
    if not value:
        pytest.skip("AIR_TEST_ADMIN_DATABASE_URL not configured")
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("AIR_TEST_ADMIN_DATABASE_URL must be PostgreSQL")
    return value


@pytest.fixture(autouse=True)
def isolate_admin_import(postgres_url):
    """Keep this test's admin rows/manifest separate from other PG tests."""
    engine = create_engine(postgres_url)
    tables = ("air_admin_audit", "air_admin_login_limits", "air_admin_sessions", "air_admin_users")
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM air_domain_store_imports WHERE import_name='sqlite_admin_auth_v1'"))
            for table in tables:
                conn.execute(text(f"DELETE FROM {table}"))
        yield
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM air_domain_store_imports WHERE import_name='sqlite_admin_auth_v1'"))
            for table in tables:
                conn.execute(text(f"DELETE FROM {table}"))
        engine.dispose()


def _source(path: Path, encrypted_mfa: bytes):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE air_admin_users(
      admin_id TEXT PRIMARY KEY,email TEXT,password_hash TEXT,mfa_secret BLOB,role TEXT,
      is_active INTEGER,created_at TEXT,last_totp_counter INTEGER,must_change_password INTEGER,
      failed_attempts INTEGER,locked_until INTEGER);
    CREATE TABLE air_admin_sessions(session_id TEXT PRIMARY KEY,admin_id TEXT,active INTEGER,created_at TEXT);
    CREATE TABLE air_admin_login_limits(rate_key TEXT PRIMARY KEY,failures INTEGER,window_started INTEGER,locked_until INTEGER);
    CREATE TABLE air_admin_audit(event_id TEXT PRIMARY KEY,actor_admin_id TEXT,action TEXT,target_admin_id TEXT,details TEXT,created_at TEXT);
    """)
    db.execute("INSERT INTO air_admin_users VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               ("admin-1","root@example.com","argon-hash",encrypted_mfa,"SUPER_ADMIN",1,
                "2026-01-01 00:00:00",123,0,0,0))
    db.execute("INSERT INTO air_admin_sessions VALUES(?,?,?,?)",
               ("session-1","admin-1",1,"2026-01-01 00:00:00"))
    db.execute("INSERT INTO air_admin_login_limits VALUES(?,?,?,?)", ("rate-1",2,100,0))
    db.execute("INSERT INTO air_admin_audit VALUES(?,?,?,?,?,?)",
               ("event-1","admin-1","BOOTSTRAP","admin-1","root","2026-01-01 00:00:00"))
    db.commit()
    db.close()


def test_transfer_preserves_admin_rows_and_encrypted_mfa(postgres_url, tmp_path, monkeypatch):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("AIR_ADMIN_MFA_KEY", key.decode())
    encrypted_mfa = cipher.encrypt(b"JBSWY3DPEHPK3PXP")
    source = tmp_path / "source.sqlite3"
    _source(source, encrypted_mfa)
    engine = create_engine(postgres_url)
    try:
        counts = migrate(str(source), postgres_url)
        assert counts == {"air_admin_users":1,"air_admin_sessions":1,
                          "air_admin_login_limits":1,"air_admin_audit":1}
        with engine.connect() as conn:
            row = conn.execute(text("SELECT password_hash,mfa_secret FROM air_admin_users WHERE admin_id='admin-1'")).one()
            assert row.password_hash == "argon-hash"
            assert bytes(row.mfa_secret) == encrypted_mfa
            assert cipher.decrypt(bytes(row.mfa_secret)) == b"JBSWY3DPEHPK3PXP"
    finally:
        engine.dispose()


def test_conflicting_target_row_rolls_back_transfer(postgres_url, tmp_path, monkeypatch):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("AIR_ADMIN_MFA_KEY", key.decode())
    source = tmp_path / "source.sqlite3"
    _source(source, cipher.encrypt(b"JBSWY3DPEHPK3PXP"))
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO air_admin_users
                (admin_id,email,password_hash,mfa_secret,role,is_active,created_at)
                VALUES ('admin-1','root@example.com','different',decode('','hex'),'SUPER_ADMIN',true,now())"""))
        with pytest.raises(RuntimeError, match="Data conflict"):
            migrate(str(source), postgres_url)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM air_admin_sessions")).scalar_one() == 0
    finally:
        engine.dispose()
