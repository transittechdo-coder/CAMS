"""User accounts and login sessions.

Roles:
* admin    - everything, including users, settings and deleting people
* operator - enrol people, manage cameras and the map, search
* viewer   - live view, search and alerts only
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from .db import Database

ITERATIONS = 240_000
SESSION_SECONDS = 12 * 3600
ROLES = ("admin", "operator", "viewer")
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def validate_password(password: str) -> str | None:
    """Return an error message, or None if the password is acceptable."""
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password.isdigit() or password.isalpha():
        return "Use a mix of letters and numbers."
    return None


def has_users(db: Database) -> bool:
    return db.one("SELECT 1 AS x FROM users LIMIT 1") is not None


def create_user(db: Database, username: str, password: str, role: str, full_name: str = "") -> int:
    if role not in ROLES:
        raise ValueError("Unknown role")
    return db.execute(
        "INSERT INTO users(username, full_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (username.strip(), full_name.strip(), hash_password(password), role, time.time()),
    )


def login(db: Database, username: str, password: str) -> str | None:
    user = db.one("SELECT * FROM users WHERE username = ?", (username.strip(),))
    if not user or not verify_password(password, user["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user["id"], time.time() + SESSION_SECONDS),
    )
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    return token


def logout(db: Database, token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def user_for_token(db: Database, token: str | None) -> dict | None:
    if not token:
        return None
    row = db.one(
        "SELECT u.id, u.username, u.full_name, u.role, s.expires_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    )
    if not row or row["expires_at"] < time.time():
        return None
    return row


def role_at_least(user: dict, role: str) -> bool:
    return ROLE_RANK.get(user.get("role", ""), -1) >= ROLE_RANK[role]
