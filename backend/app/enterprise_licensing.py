"""Offline-verifiable enterprise licences bound to AIR organisation deployments.

The issuing private key is held only by the licence issuer. AIR installations
ship the public verification key and validate signed licence files locally.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date, datetime, timezone
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import create_engine, text

from app.commercial_catalogue import RESTRICTED_FEATURES, catalogue_plan
from app.deployment_profiles import load_profile

LICENSE_STATES = {"ACTIVE", "GRACE", "SUSPENDED", "REVOKED", "EXPIRED"}
ALLOWED_PROFILES = {"onprem-single", "aws-private-single", "aws-saas-multi"}


class EnterpriseLicenseError(ValueError):
    pass


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise EnterpriseLicenseError("Invalid base64 key material") from exc


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def fingerprint_digest(fingerprint: str) -> str:
    value = str(fingerprint or "").strip()
    if len(value) < 16 or len(value) > 4096:
        raise EnterpriseLicenseError("Deployment fingerprint must contain 16-4096 characters")
    return hashlib.sha256(value.encode()).hexdigest()


def sign_license(payload: dict, private_key_b64: str) -> str:
    raw = _b64decode(private_key_b64)
    if len(raw) != 32:
        raise EnterpriseLicenseError("Ed25519 private key must be 32 raw bytes")
    signature = Ed25519PrivateKey.from_private_bytes(raw).sign(_canonical(payload))
    return base64.urlsafe_b64encode(_canonical({"payload": payload, "signature": base64.urlsafe_b64encode(signature).decode().rstrip("=")})).decode().rstrip("=")


def verify_license(token: str, public_key_b64: str, *, tenant_id: str,
                   deployment_id: str, profile_id: str, fingerprint: str,
                   today: date | None = None) -> dict:
    try:
        envelope = json.loads(_b64decode(token))
        payload = envelope["payload"]
        signature = _b64decode(envelope["signature"])
        public_raw = _b64decode(public_key_b64)
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, _canonical(payload))
    except (KeyError, ValueError, TypeError, InvalidSignature) as exc:
        raise EnterpriseLicenseError("Enterprise licence signature is invalid") from exc
    if payload.get("tenant_id") != tenant_id or payload.get("deployment_id") != deployment_id:
        raise EnterpriseLicenseError("Enterprise licence is not bound to this organisation and deployment")
    if payload.get("profile_id") != profile_id:
        raise EnterpriseLicenseError("Enterprise licence deployment profile does not match this installation")
    if payload.get("fingerprint_sha256") != fingerprint_digest(fingerprint):
        raise EnterpriseLicenseError("Enterprise licence fingerprint does not match this installation")
    if payload.get("status") not in {"ACTIVE", "GRACE"}:
        raise EnterpriseLicenseError("Enterprise licence is not active")
    current = today or date.today()
    start = date.fromisoformat(payload["valid_from"])
    end = date.fromisoformat(payload["valid_until"])
    grace = date.fromisoformat(payload["grace_until"]) if payload.get("grace_until") else None
    if current < start:
        raise EnterpriseLicenseError("Enterprise licence is not yet valid")
    if current >= end and (payload.get("status") != "GRACE" or not grace or current > grace):
        raise EnterpriseLicenseError("Enterprise licence has expired")
    features = set(payload.get("features", []))
    if features.intersection(RESTRICTED_FEATURES):
        raise EnterpriseLicenseError("Licence contains globally restricted capabilities")
    return payload


class EnterpriseLicenseStore:
    def __init__(self, database_url: str | None = None, sqlite_path: str | None = None):
        database_url = database_url if database_url is not None else os.getenv("AIR_CUSTOMER_DATABASE_URL", "")
        sqlite_path = sqlite_path or os.getenv("AIR_LICENSE_DB_PATH", "data/enterprise_licensing.sqlite3")
        if database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            self.engine = create_engine(database_url, pool_pre_ping=True, future=True)
            self.postgres = True
        elif database_url:
            raise RuntimeError("AIR_CUSTOMER_DATABASE_URL must use PostgreSQL")
        else:
            os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)
            self.engine = create_engine("sqlite:///" + os.path.abspath(sqlite_path), future=True)
            self.postgres = False
            self._sqlite_schema()

    def _scope(self):
        from app.tenant_context import tenant_scope
        return tenant_scope(is_admin=True)

    def _sqlite_schema(self):
        with self.engine.begin() as conn:
            conn.execute(text("""CREATE TABLE IF NOT EXISTS air_deployment_instances(
                deployment_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, instance_key TEXT NOT NULL,
                profile_id TEXT NOT NULL, provider TEXT NOT NULL, tenancy TEXT NOT NULL,
                fingerprint_sha256 TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                UNIQUE(tenant_id,instance_key))"""))
            conn.execute(text("""CREATE TABLE IF NOT EXISTS air_enterprise_licenses(
                license_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, contract_id TEXT NOT NULL,
                license_code TEXT NOT NULL UNIQUE, plan_code TEXT NOT NULL, status TEXT NOT NULL,
                max_seats INTEGER NOT NULL, max_deployments INTEGER NOT NULL, features TEXT NOT NULL,
                allowed_profiles TEXT NOT NULL, valid_from TEXT NOT NULL, valid_until TEXT NOT NULL,
                grace_until TEXT, issued_at TEXT NOT NULL, revoked_at TEXT,
                UNIQUE(tenant_id,license_id))"""))
            conn.execute(text("""CREATE TABLE IF NOT EXISTS air_license_bindings(
                binding_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, license_id TEXT NOT NULL,
                deployment_id TEXT NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                bound_at TEXT NOT NULL, unbound_at TEXT,
                UNIQUE(tenant_id,idempotency_key), UNIQUE(license_id,deployment_id))"""))
            conn.execute(text("""CREATE TABLE IF NOT EXISTS air_enterprise_license_events(
                event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, license_id TEXT NOT NULL,
                actor_id TEXT NOT NULL, event_type TEXT NOT NULL, details TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, occurred_at TEXT NOT NULL,
                UNIQUE(tenant_id,idempotency_key))"""))

    def register_deployment(self, *, tenant_id: str, instance_key: str, profile_id: str,
                            fingerprint: str, label: str = "AIR deployment") -> dict:
        if profile_id not in ALLOWED_PROFILES:
            raise EnterpriseLicenseError("Unsupported AIR deployment profile")
        profile = load_profile(profile_id)
        digest = fingerprint_digest(fingerprint)
        instance = str(instance_key or "").strip()
        if not instance or len(instance) > 128:
            raise EnterpriseLicenseError("A stable deployment instance key is required")
        now = datetime.now(timezone.utc).isoformat()
        deployment_id = str(uuid4())
        with self._scope(), self.engine.begin() as conn:
            suffix = " FOR UPDATE" if self.postgres else ""
            old = conn.execute(text("SELECT * FROM air_deployment_instances WHERE tenant_id=:t AND instance_key=:k" + suffix),
                               {"t": tenant_id, "k": instance}).mappings().first()
            if old:
                if old["fingerprint_sha256"] != digest or old["profile_id"] != profile_id:
                    raise EnterpriseLicenseError("Deployment instance identity cannot be changed; register a new instance")
                conn.execute(text("UPDATE air_deployment_instances SET last_seen_at=:now,label=:label WHERE deployment_id=:id"),
                             {"now": now, "label": label[:160], "id": old["deployment_id"]})
                return dict(old) | {"last_seen_at": now}
            conn.execute(text("""INSERT INTO air_deployment_instances
                (deployment_id,tenant_id,instance_key,profile_id,provider,tenancy,
                 fingerprint_sha256,label,status,created_at,last_seen_at)
                VALUES(:id,:t,:k,:p,:provider,:tenancy,:fp,:label,'ACTIVE',:now,:now)"""),
                {"id": deployment_id, "t": tenant_id, "k": instance, "p": profile_id,
                 "provider": profile["deployment"]["provider"], "tenancy": profile["deployment"]["tenancy"],
                 "fp": digest, "label": label[:160], "now": now})
        return {"deployment_id": deployment_id, "tenant_id": tenant_id, "instance_key": instance,
                "profile_id": profile_id, "provider": profile["deployment"]["provider"],
                "tenancy": profile["deployment"]["tenancy"], "fingerprint_sha256": digest,
                "label": label[:160], "status": "ACTIVE", "created_at": now, "last_seen_at": now}

    def issue_and_bind(self, *, tenant_id: str, contract_id: str, deployment_id: str,
                       max_seats: int, max_deployments: int, valid_from: date,
                       valid_until: date, grace_until: date | None, actor_id: str,
                       idempotency_key: str, private_key_b64: str) -> dict:
        if valid_until <= valid_from or (grace_until and grace_until < valid_until):
            raise EnterpriseLicenseError("Licence validity dates are inconsistent")
        if max_seats < 1 or max_deployments < 1 or max_deployments > 100:
            raise EnterpriseLicenseError("Seat and deployment limits must be positive and bounded")
        if not idempotency_key or len(idempotency_key) > 200:
            raise EnterpriseLicenseError("A bounded idempotency key is required")
        with self._scope(), self.engine.begin() as conn:
            suffix = " FOR UPDATE" if self.postgres else ""
            contract = conn.execute(text("SELECT * FROM air_commercial_contracts WHERE tenant_id=:t AND contract_id=:c" + suffix),
                                     {"t": tenant_id, "c": contract_id}).mappings().first()
            if not contract:
                raise KeyError("Commercial contract not found")
            if contract["status"] != "ACTIVE":
                raise EnterpriseLicenseError("Only ACTIVE enterprise contracts can receive a licence")
            plan = catalogue_plan(contract["plan_code"])
            if not plan or not contract["plan_code"].startswith("B2B_"):
                raise EnterpriseLicenseError("Enterprise licences require a recognised B2B plan")
            deployment = conn.execute(text("SELECT * FROM air_deployment_instances WHERE tenant_id=:t AND deployment_id=:d" + suffix),
                                      {"t": tenant_id, "d": deployment_id}).mappings().first()
            if not deployment or deployment["status"] != "ACTIVE":
                raise EnterpriseLicenseError("An active deployment registered to this organisation is required")
            existing = conn.execute(text("SELECT * FROM air_license_bindings WHERE tenant_id=:t AND idempotency_key=:k"),
                                    {"t": tenant_id, "k": idempotency_key}).mappings().first()
            if existing:
                license_row = conn.execute(text("SELECT * FROM air_enterprise_licenses WHERE tenant_id=:t AND license_id=:l"),
                                           {"t": tenant_id, "l": existing["license_id"]}).mappings().first()
                return dict(license_row) | {"binding_id": existing["binding_id"], "idempotent_replay": True}
            count = conn.execute(text("""SELECT COUNT(*) FROM air_license_bindings b
                JOIN air_enterprise_licenses l ON l.license_id=b.license_id
                WHERE b.license_id IN (SELECT license_id FROM air_enterprise_licenses WHERE tenant_id=:t)
                  AND b.status='ACTIVE' AND l.status IN ('ACTIVE','GRACE')"""), {"t": tenant_id}).scalar_one()
            if int(count) >= max_deployments:
                raise EnterpriseLicenseError("Enterprise licence deployment limit reached")
            features = sorted(set(plan["features"]) - RESTRICTED_FEATURES)
            license_id, license_code = str(uuid4()), "AIR-" + uuid4().hex.upper()
            now = datetime.now(timezone.utc).isoformat()
            features_sql = "CAST(:features AS json)" if self.postgres else ":features"
            profiles = [deployment["profile_id"]]
            profiles_sql = "CAST(:profiles AS json)" if self.postgres else ":profiles"
            conn.execute(text(f"""INSERT INTO air_enterprise_licenses
                (license_id,tenant_id,contract_id,license_code,plan_code,status,max_seats,max_deployments,
                 features,allowed_profiles,valid_from,valid_until,grace_until,issued_at)
                VALUES(:id,:t,:c,:code,:plan,'ACTIVE',:seats,:deployments,{features_sql},{profiles_sql},
                       :start,:end,:grace,:now)"""),
                {"id": license_id, "t": tenant_id, "c": contract_id, "code": license_code,
                 "plan": contract["plan_code"], "seats": max_seats, "deployments": max_deployments,
                 "features": json.dumps(features), "profiles": json.dumps(profiles),
                 "start": valid_from.isoformat(), "end": valid_until.isoformat(),
                 "grace": grace_until.isoformat() if grace_until else None, "now": now})
            binding_id = str(uuid4())
            conn.execute(text("""INSERT INTO air_license_bindings
                (binding_id,tenant_id,license_id,deployment_id,status,idempotency_key,bound_at)
                VALUES(:b,:t,:l,:d,'ACTIVE',:k,:now)"""),
                {"b": binding_id, "t": tenant_id, "l": license_id, "d": deployment_id,
                 "k": idempotency_key, "now": now})
            details_sql = "CAST(:details AS json)" if self.postgres else ":details"
            conn.execute(text(f"""INSERT INTO air_enterprise_license_events
                (event_id,tenant_id,license_id,actor_id,event_type,details,idempotency_key,occurred_at)
                VALUES(:e,:t,:l,:actor,'LICENSE_ISSUED_AND_BOUND',{details_sql},:k,:now)"""),
                {"e": str(uuid4()), "t": tenant_id, "l": license_id, "actor": actor_id,
                 "details": json.dumps({"contract_id": contract_id, "deployment_id": deployment_id,
                                        "max_seats": max_seats, "max_deployments": max_deployments}),
                 "k": idempotency_key, "now": now})
            payload = {"schema_version": 1, "license_id": license_id, "license_code": license_code,
                       "tenant_id": tenant_id, "contract_id": contract_id, "deployment_id": deployment_id,
                       "profile_id": deployment["profile_id"], "fingerprint_sha256": deployment["fingerprint_sha256"],
                       "plan_code": contract["plan_code"], "status": "ACTIVE", "max_seats": max_seats,
                       "features": features, "valid_from": valid_from.isoformat(),
                       "valid_until": valid_until.isoformat(),
                       "grace_until": grace_until.isoformat() if grace_until else None}
            token = sign_license(payload, private_key_b64)
        return {"license_id": license_id, "license_code": license_code, "tenant_id": tenant_id,
                "contract_id": contract_id, "deployment_id": deployment_id, "plan_code": contract["plan_code"],
                "status": "ACTIVE", "max_seats": max_seats, "max_deployments": max_deployments,
                "features": features, "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(), "grace_until": grace_until.isoformat() if grace_until else None,
                "binding_id": binding_id, "license_token": token, "idempotent_replay": False}

    def active_license(self, tenant_id: str, deployment_id: str) -> dict | None:
        with self._scope(), self.engine.connect() as conn:
            row = conn.execute(text("""SELECT l.*,b.binding_id,d.profile_id,d.fingerprint_sha256
                FROM air_enterprise_licenses l JOIN air_license_bindings b ON b.license_id=l.license_id
                JOIN air_deployment_instances d ON d.deployment_id=b.deployment_id
                WHERE l.tenant_id=:t AND d.tenant_id=:t AND b.deployment_id=:d
                  AND b.status='ACTIVE' AND l.status IN ('ACTIVE','GRACE')
                ORDER BY l.issued_at DESC LIMIT 1"""), {"t": tenant_id, "d": deployment_id}).mappings().first()
        return dict(row) if row else None

    def revoke(self, tenant_id: str, license_id: str, actor_id: str, idempotency_key: str) -> None:
        with self._scope(), self.engine.begin() as conn:
            row = conn.execute(text("SELECT status FROM air_enterprise_licenses WHERE tenant_id=:t AND license_id=:l"),
                               {"t": tenant_id, "l": license_id}).first()
            if not row:
                raise KeyError("Enterprise licence not found")
            if row[0] == "REVOKED":
                return
            conn.execute(text("UPDATE air_enterprise_licenses SET status='REVOKED',revoked_at=:now WHERE tenant_id=:t AND license_id=:l"),
                         {"now": datetime.now(timezone.utc).isoformat(), "t": tenant_id, "l": license_id})
            conn.execute(text("UPDATE air_license_bindings SET status='REVOKED',unbound_at=:now WHERE tenant_id=:t AND license_id=:l"),
                         {"now": datetime.now(timezone.utc).isoformat(), "t": tenant_id, "l": license_id})
            details_sql = "CAST(:details AS json)" if self.postgres else ":details"
            conn.execute(text(f"""INSERT INTO air_enterprise_license_events
                (event_id,tenant_id,license_id,actor_id,event_type,details,idempotency_key,occurred_at)
                VALUES(:e,:t,:l,:actor,'LICENSE_REVOKED',{details_sql},:k,:now)"""),
                {"e": str(uuid4()), "t": tenant_id, "l": license_id, "actor": actor_id,
                 "details": "{}", "k": idempotency_key, "now": datetime.now(timezone.utc).isoformat()})
