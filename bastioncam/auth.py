from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone


ISSUER = "bastioncam"
AUDIENCE = "bastioncam-ingest"


class TokenError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(value: str, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())


def signing_secret(db: sqlite3.Connection) -> str:
    row = db.execute("SELECT value FROM server_settings WHERE key='jwt_signing_secret'").fetchone()
    if row:
        return row[0]
    value = secrets.token_urlsafe(48)
    db.execute("INSERT INTO server_settings(key,value) VALUES('jwt_signing_secret',?)", (value,))
    db.commit()
    return value


def create_collector(db: sqlite3.Connection, name: str) -> tuple[dict, str]:
    name = " ".join(name.strip().split())
    if not name or len(name) > 120:
        raise ValueError("name must contain 1–120 characters")
    collector_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("INSERT INTO collectors(id,name,created_at) VALUES(?,?,?)",
               (collector_id, name, created_at))
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(json.dumps({
        "iss": ISSUER, "aud": AUDIENCE, "sub": collector_id, "name": name,
        "iat": int(datetime.now(timezone.utc).timestamp()), "jti": str(uuid.uuid4()),
    }, separators=(",", ":")).encode())
    unsigned = f"{header}.{payload}"
    token = f"{unsigned}.{_sign(unsigned, signing_secret(db))}"
    db.commit()
    return {"id": collector_id, "name": name, "created_at": created_at}, token


def register_embedded_collector(db: sqlite3.Connection, hostname: str, seen_at: str) -> dict:
    name = f"{hostname} (embedded)"
    collector_id = f"embedded:{uuid.uuid5(uuid.NAMESPACE_DNS, hostname)}"
    db.execute("""INSERT INTO collectors(id,name,created_at,last_seen_at)
        VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        name=excluded.name,last_seen_at=excluded.last_seen_at,disabled=0""",
        (collector_id, name, seen_at, seen_at))
    return {"id": collector_id, "name": name, "created_at": seen_at,
            "last_seen_at": seen_at, "disabled": 0}


def authenticate(db: sqlite3.Connection, authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise TokenError("missing bearer token")
    token = authorization[7:].strip()
    try:
        header_part, payload_part, signature = token.split(".")
        header = json.loads(_b64decode(header_part))
        payload = json.loads(_b64decode(payload_part))
    except Exception as error:
        raise TokenError("malformed token") from error
    if header != {"alg": "HS256", "typ": "JWT"}:
        raise TokenError("unsupported token header")
    unsigned = f"{header_part}.{payload_part}"
    if not hmac.compare_digest(signature, _sign(unsigned, signing_secret(db))):
        raise TokenError("invalid token signature")
    if payload.get("iss") != ISSUER or payload.get("aud") != AUDIENCE or not payload.get("sub"):
        raise TokenError("invalid token claims")
    row = db.execute("SELECT * FROM collectors WHERE id=?",
                     (payload["sub"],)).fetchone()
    if not row:
        raise TokenError("unknown collector")
    if row["revoked_at"]:
        raise TokenError("revoked collector")
    if row["disabled"]:
        raise TokenError("disabled collector")
    return dict(row)
