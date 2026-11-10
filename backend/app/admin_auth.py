"""Role-based AIR administrator authentication with TOTP MFA and revocable sessions."""
from __future__ import annotations
import base64, hashlib, hmac, os, secrets, sqlite3, struct, time
from pathlib import Path
from uuid import uuid4
from cryptography.fernet import Fernet
from app.security import hash_password, verify_password

class AdminAuthStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AIR_AUTH_DB_PATH", "data/air_auth.sqlite3")
        if self.db_path != ":memory:": Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_admin_users(
            admin_id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,mfa_secret BLOB NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('SUPER_ADMIN','ADMIN','RESEARCH_ADMIN')),
            is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS air_admin_sessions(
            session_id TEXT PRIMARY KEY,admin_id TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.db.commit()
        key_file=os.getenv("AIR_ADMIN_MFA_KEY_FILE")
        key=Path(key_file).read_bytes().strip() if key_file else os.getenv("AIR_ADMIN_MFA_KEY","").encode()
        if not key: raise RuntimeError("AIR_ADMIN_MFA_KEY_FILE must contain a Fernet key")
        self.cipher=Fernet(key)

    def bootstrap(self,email:str,password:str,secret:str|None=None)->tuple[str,str]:
        email=email.strip().lower()
        if not email or "@" not in email: raise ValueError("A valid administrator email is required")
        if self.db.execute("SELECT 1 FROM air_admin_users LIMIT 1").fetchone():
            raise ValueError("Administrator bootstrap is already complete")
        secret=secret or base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        admin_id=str(uuid4())
        encrypted=self.cipher.encrypt(secret.encode())
        with self.db:
            self.db.execute("INSERT INTO air_admin_users(admin_id,email,password_hash,mfa_secret,role) VALUES(?,?,?,?,?)",
                (admin_id,email,hash_password(password),encrypted,"SUPER_ADMIN"))
        return admin_id,secret

    def authenticate(self,email:str,password:str,code:str)->dict|None:
        row=self.db.execute("SELECT * FROM air_admin_users WHERE email=? AND is_active=1",(email.strip().lower(),)).fetchone()
        if not row or not verify_password(password,row["password_hash"]): return None
        secret=self.cipher.decrypt(row["mfa_secret"]).decode()
        if not verify_totp(secret,code): return None
        sid=str(uuid4())
        with self.db: self.db.execute("INSERT INTO air_admin_sessions(session_id,admin_id) VALUES(?,?)",(sid,row["admin_id"]))
        return {"admin_id":row["admin_id"],"email":row["email"],"role":row["role"],"session_id":sid}

    def session(self,session_id:str):
        return self.db.execute("""SELECT u.admin_id,u.email,u.role FROM air_admin_sessions s
            JOIN air_admin_users u ON u.admin_id=s.admin_id
            WHERE s.session_id=? AND s.active=1 AND u.is_active=1""",(session_id,)).fetchone()

    def revoke(self,session_id:str)->None:
        with self.db: self.db.execute("UPDATE air_admin_sessions SET active=0 WHERE session_id=?",(session_id,))

    def close(self): self.db.close()

def verify_totp(secret:str,code:str,now:int|None=None)->bool:
    if len(code)!=6 or not code.isdigit(): return False
    try:
        key=base64.b32decode(secret + "="*((8-len(secret)%8)%8),casefold=True)
    except Exception: return False
    counter=int((now if now is not None else time.time())//30)
    for step in (-1,0,1):
        digest=hmac.new(key,struct.pack(">Q",counter+step),hashlib.sha1).digest()
        offset=digest[-1]&15
        value=(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000
        if hmac.compare_digest(f"{value:06d}",code): return True
    return False


_admin_store = None

def get_admin_auth_store() -> AdminAuthStore:
    global _admin_store
    if _admin_store is None:
        _admin_store = AdminAuthStore()
    return _admin_store
