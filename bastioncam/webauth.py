from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone


SESSION_SECONDS = 7 * 24 * 60 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_username(username: str) -> str:
    username = username.strip()
    if not username or len(username) > 80 or any(c.isspace() for c in username):
        raise ValueError("username must contain 1–80 characters without spaces")
    return username


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                                n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def create_user(db: sqlite3.Connection, username: str, password: str) -> dict:
    username = normalize_username(username)
    created_at = _now().isoformat(timespec="seconds")
    cursor = db.execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                        (username, hash_password(password), created_at))
    db.commit()
    return {"id": cursor.lastrowid, "username": username, "created_at": created_at}


def check_credentials(db: sqlite3.Connection, username: str, password: str) -> dict | None:
    row = db.execute("SELECT id,username,password_hash,created_at FROM users WHERE username=?",
                     (username.strip(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"], "created_at": row["created_at"]}


def create_session(db: sqlite3.Connection, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = _now(); expires = now + timedelta(seconds=SESSION_SECONDS)
    db.execute("DELETE FROM web_sessions WHERE expires_at<=?", (now.isoformat(),))
    db.execute("INSERT INTO web_sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf,
                now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")))
    db.commit()
    return token, csrf


def session_user(db: sqlite3.Connection, token: str) -> dict | None:
    if not token:
        return None
    now = _now().isoformat()
    row = db.execute("""SELECT u.id,u.username,u.created_at,s.csrf_token,s.expires_at
        FROM web_sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=? AND s.expires_at>?""",
        (hashlib.sha256(token.encode()).hexdigest(), now)).fetchone()
    return dict(row) if row else None


def delete_session(db: sqlite3.Connection, token: str) -> None:
    if token:
        db.execute("DELETE FROM web_sessions WHERE token_hash=?",
                   (hashlib.sha256(token.encode()).hexdigest(),))
        db.commit()
