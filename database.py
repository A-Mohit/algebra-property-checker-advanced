"""Persistence layer: Supabase/Postgres in production, SQLite for local development.

Production credentials are read from Streamlit secrets or environment variables.
Never commit service-role credentials to source control.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).with_name("algebra_data.db")
ITERATIONS = 310_000


def _setting(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return default


def _supabase_configured() -> bool:
    return bool(_setting("SUPABASE_URL") and _setting("SUPABASE_SERVICE_ROLE_KEY"))


def _supabase():
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError("Supabase support is missing. Install dependencies from requirements.txt.") from exc
    return create_client(_setting("SUPABASE_URL"), _setting("SUPABASE_SERVICE_ROLE_KEY"))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def storage_backend() -> str:
    return "Supabase (persistent hosted database)" if _supabase_configured() else "SQLite (local development only)"


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return salt.hex(), digest.hex()


def _ensure_sqlite_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    additions = {
        "email": "TEXT",
        "status": "TEXT NOT NULL DEFAULT 'approved'",
        "is_admin": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email) WHERE email IS NOT NULL")
    conn.execute("""CREATE TABLE IF NOT EXISTS password_resets (
        email TEXT PRIMARY KEY, token_hash TEXT NOT NULL, expires_at TEXT NOT NULL
    )""")
    for table in ("theorems", "algebras"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")


def _ensure_root_admin():
    username = (_setting("ROOT_ADMIN_USERNAME") or "").strip().lower()
    email = (_setting("ROOT_ADMIN_EMAIL") or "").strip().lower()
    password = _setting("ROOT_ADMIN_PASSWORD") or ""
    if not (username and email and password):
        return
    if len(password) < 14:
        raise RuntimeError("ROOT_ADMIN_PASSWORD must contain at least 14 characters.")
    salt, digest = _hash_password(password)
    if _supabase_configured():
        client = _supabase()
        found = client.table("users").select("username,is_admin").eq("username", username).limit(1).execute().data
        payload = {"username": username, "email": email, "password_salt": salt,
                   "password_hash": digest, "status": "approved", "is_admin": True}
        if found:
            # Keep admin password in sync with deployment secret; do not downgrade admin.
            client.table("users").update(payload).eq("username", username).execute()
        else:
            client.table("users").insert(payload).execute()
    else:
        with get_connection() as conn:
            conn.execute("""INSERT INTO users(username,email,password_salt,password_hash,status,is_admin)
                VALUES(?,?,?,?, 'approved',1) ON CONFLICT(username) DO UPDATE SET
                email=excluded.email,password_salt=excluded.password_salt,
                password_hash=excluded.password_hash,status='approved',is_admin=1""",
                (username, email, salt, digest))


def initialize_database():
    if _supabase_configured():
        client = _supabase()
        for table in ("users", "theorems", "algebras", "password_resets"):
            client.table(table).select("*").limit(1).execute()
    else:
        with get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS theorems (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT NOT NULL,
                variable_count INTEGER NOT NULL, lhs TEXT NOT NULL, rhs TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,name,lhs,rhs),
                FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS algebras (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT NOT NULL,
                elements_json TEXT NOT NULL, theta_json TEXT NOT NULL, phi_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,name),
                FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE)""")
            _ensure_sqlite_columns(conn)
    _ensure_root_admin()


def register_user(username: str, email: str, password: str) -> tuple[bool, str]:
    username = username.strip().lower()
    email = email.strip().lower()
    if not 3 <= len(username) <= 32 or not re.fullmatch(r"[a-z0-9_-]+", username):
        return False, "Username must be 3–32 characters using letters, numbers, underscores, or hyphens."
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return False, "Enter a valid email address."
    if len(password) < 10:
        return False, "Use a password with at least 10 characters."
    salt, digest = _hash_password(password)
    try:
        payload = {"username": username, "email": email, "password_salt": salt,
                   "password_hash": digest, "status": "pending", "is_admin": False}
        if _supabase_configured():
            _supabase().table("users").insert(payload).execute()
        else:
            with get_connection() as conn:
                conn.execute("""INSERT INTO users(username,email,password_salt,password_hash,status,is_admin)
                    VALUES(?,?,?,?, 'pending',0)""", (username,email,salt,digest))
                conn.execute("UPDATE theorems SET user_id=? WHERE user_id IS NULL", (username,))
                conn.execute("UPDATE algebras SET user_id=? WHERE user_id IS NULL", (username,))
        return True, "Registration submitted. Your account is pending root-admin approval."
    except Exception as exc:
        msg = str(exc).lower()
        if any(x in msg for x in ("duplicate", "unique", "already exists", "23505")):
            return False, "That username or email is already registered."
        raise


def _find_user(identifier: str):
    identifier = identifier.strip().lower()
    if _supabase_configured():
        client = _supabase()
        rows = client.table("users").select("*").eq("username", identifier).limit(1).execute().data
        if not rows:
            rows = client.table("users").select("*").eq("email", identifier).limit(1).execute().data
        return rows[0] if rows else None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE LIMIT 1",
                           (identifier, identifier)).fetchone()
        return dict(row) if row else None


def authenticate_user(identifier: str, password: str):
    row = _find_user(identifier)
    if not row:
        return False, None, "Incorrect username/email or password."
    _, candidate = _hash_password(password, bytes.fromhex(row["password_salt"]))
    if not hmac.compare_digest(candidate, row["password_hash"]):
        return False, None, "Incorrect username/email or password."
    if row.get("status") != "approved":
        if row.get("status") == "suspended":
            return False, None, "This account is suspended. Contact the administrator."
        return False, None, "Your account is pending root-admin approval."
    return True, {"username": row["username"], "email": row.get("email"), "is_admin": bool(row.get("is_admin"))}, "Login successful."


def list_all_users():
    if _supabase_configured():
        return _supabase().table("users").select("username,email,status,is_admin,created_at").order("created_at", desc=True).execute().data
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT username,email,status,is_admin,created_at FROM users ORDER BY created_at DESC").fetchall()]


def set_user_status(username: str, status: str):
    if status not in {"approved", "pending", "suspended"}:
        raise ValueError("Invalid account status.")
    if _supabase_configured():
        _supabase().table("users").update({"status": status}).eq("username", username).eq("is_admin", False).execute()
    else:
        with get_connection() as conn:
            conn.execute("UPDATE users SET status=? WHERE username=? AND is_admin=0", (status, username))


def _send_reset_email(email: str, token: str):
    host = _setting("SMTP_HOST")
    user = _setting("SMTP_USERNAME")
    password = _setting("SMTP_PASSWORD")
    sender = _setting("SMTP_FROM") or user
    if not all((host, user, password, sender)):
        raise RuntimeError("Password reset email is not configured. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM in Streamlit Secrets.")
    msg = EmailMessage()
    msg["Subject"] = "Algebra Engine password reset code"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(f"Your password reset code is: {token}\n\nIt expires in 15 minutes. If you did not request this, ignore this email.")
    with smtplib.SMTP(host, int(_setting("SMTP_PORT", "587"))) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


def request_password_reset(email: str):
    email = email.strip().lower()
    row = _find_user(email)
    # Avoid revealing whether an email is registered.
    if not row:
        return True, "If that email belongs to an account, a reset code will be sent."
    token = f"{secrets.randbelow(1000000):06d}"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    if _supabase_configured():
        _supabase().table("password_resets").upsert({"email": email, "token_hash": token_hash, "expires_at": expires}, on_conflict="email").execute()
    else:
        with get_connection() as conn:
            conn.execute("INSERT INTO password_resets(email,token_hash,expires_at) VALUES(?,?,?) ON CONFLICT(email) DO UPDATE SET token_hash=excluded.token_hash,expires_at=excluded.expires_at", (email,token_hash,expires))
    _send_reset_email(email, token)
    return True, "If that email belongs to an account, a reset code will be sent."


def complete_password_reset(email: str, token: str, new_password: str):
    email = email.strip().lower()
    if len(new_password) < 10:
        return False, "New password must contain at least 10 characters."
    if _supabase_configured():
        rows = _supabase().table("password_resets").select("*").eq("email", email).limit(1).execute().data
        reset = rows[0] if rows else None
    else:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM password_resets WHERE email=?", (email,)).fetchone()
            reset = dict(row) if row else None
    if not reset or not hmac.compare_digest(hashlib.sha256(token.strip().encode()).hexdigest(), reset["token_hash"]):
        return False, "Invalid or expired reset code."
    if datetime.fromisoformat(reset["expires_at"]) < datetime.now(timezone.utc):
        return False, "Invalid or expired reset code."
    salt, digest = _hash_password(new_password)
    if _supabase_configured():
        _supabase().table("users").update({"password_salt": salt, "password_hash": digest}).eq("email", email).execute()
        _supabase().table("password_resets").delete().eq("email", email).execute()
    else:
        with get_connection() as conn:
            conn.execute("UPDATE users SET password_salt=?,password_hash=? WHERE email=?", (salt,digest,email))
            conn.execute("DELETE FROM password_resets WHERE email=?", (email,))
    return True, "Password reset successfully. You can now log in."

def save_theorem(user_id, name, variable_count, lhs, rhs):
    payload = {"user_id": user_id, "name": name, "variable_count": variable_count, "lhs": lhs, "rhs": rhs}
    if _supabase_configured():
        _supabase().table("theorems").upsert(payload, on_conflict="user_id,name,lhs,rhs").execute()
    else:
        with get_connection() as conn:
            conn.execute("""INSERT INTO theorems(user_id,name,variable_count,lhs,rhs)
                VALUES(?,?,?,?,?) ON CONFLICT(user_id,name,lhs,rhs) DO UPDATE SET
                variable_count=excluded.variable_count""",
                (user_id, name, variable_count, lhs, rhs))


def list_theorems(user_id):
    if _supabase_configured():
        rows = (_supabase().table("theorems").select("*").eq("user_id", user_id)
                .order("name").execute().data)
        return rows
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM theorems WHERE user_id=? ORDER BY name", (user_id,)
        ).fetchall()]


def delete_theorem(user_id, theorem_id):
    if _supabase_configured():
        _supabase().table("theorems").delete().eq("id", theorem_id).eq("user_id", user_id).execute()
    else:
        with get_connection() as conn:
            conn.execute("DELETE FROM theorems WHERE id=? AND user_id=?", (theorem_id, user_id))


def save_algebra(user_id, name, elements, theta, phi):
    theta_rows = [[a, b, result] for (a, b), result in theta.items()]
    phi_rows = [[a, b, result] for (a, b), result in phi.items()]
    if _supabase_configured():
        payload = {"user_id": user_id, "name": name, "elements": elements,
                   "theta": theta_rows, "phi": phi_rows}
        _supabase().table("algebras").upsert(payload, on_conflict="user_id,name").execute()
    else:
        with get_connection() as conn:
            conn.execute("""INSERT INTO algebras(user_id,name,elements_json,theta_json,phi_json)
                VALUES(?,?,?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET
                elements_json=excluded.elements_json, theta_json=excluded.theta_json,
                phi_json=excluded.phi_json""",
                (user_id, name, json.dumps(elements), json.dumps(theta_rows), json.dumps(phi_rows)))


def list_algebras(user_id):
    if _supabase_configured():
        rows = (_supabase().table("algebras").select("*").eq("user_id", user_id)
                .order("name").execute().data)
        output = []
        for row in rows:
            item = dict(row)
            item["theta"] = {(a, b): value for a, b, value in item.pop("theta")}
            item["phi"] = {(a, b): value for a, b, value in item.pop("phi")}
            output.append(item)
        return output
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM algebras WHERE user_id=? ORDER BY name", (user_id,)).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["elements"] = json.loads(item.pop("elements_json"))
        item["theta"] = {(a, b): value for a, b, value in json.loads(item.pop("theta_json"))}
        item["phi"] = {(a, b): value for a, b, value in json.loads(item.pop("phi_json"))}
        output.append(item)
    return output


def delete_algebra(user_id, algebra_id):
    if _supabase_configured():
        _supabase().table("algebras").delete().eq("id", algebra_id).eq("user_id", user_id).execute()
    else:
        with get_connection() as conn:
            conn.execute("DELETE FROM algebras WHERE id=? AND user_id=?", (algebra_id, user_id))
