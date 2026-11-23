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


def initialize_database():
    if _supabase_configured():
        # Verify the hosted schema and credentials are ready. Schema is created
        # explicitly using the SQL script supplied in supabase_schema.sql.
        client = _supabase()
        for table in ("users", "theorems", "algebras"):
            client.table(table).select("*").limit(1).execute()
        return

    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS theorems (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT NOT NULL,
            variable_count INTEGER NOT NULL, lhs TEXT NOT NULL, rhs TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, name, lhs, rhs),
            FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS algebras (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT NOT NULL,
            elements_json TEXT NOT NULL, theta_json TEXT NOT NULL, phi_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE
        )""")
        # Upgrade older single-user SQLite databases without deleting saved data.
        for table in ("theorems", "algebras"):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "user_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")


def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip().lower()
    if not 3 <= len(username) <= 32:
        return False, "Username must contain 3–32 characters."
    if not re.fullmatch(r"[a-z0-9_-]+", username):
        return False, "Use only letters, numbers, underscores, and hyphens."
    if len(password) < 10:
        return False, "Use a password with at least 10 characters."
    salt, digest = _hash_password(password)
    try:
        if _supabase_configured():
            _supabase().table("users").insert({
                "username": username, "password_salt": salt, "password_hash": digest
            }).execute()
        else:
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_salt, password_hash) VALUES (?, ?, ?)",
                    (username, salt, digest),
                )
                # Preserve data from the earlier single-user local version for
                # the first account created after upgrade.
                conn.execute("UPDATE theorems SET user_id=? WHERE user_id IS NULL", (username,))
                conn.execute("UPDATE algebras SET user_id=? WHERE user_id IS NULL", (username,))
        return True, "Account created. You can now log in."
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message or "already exists" in message:
            return False, "That username is already registered. Choose another one."
        raise


def authenticate_user(username: str, password: str) -> bool:
    username = username.strip().lower()
    if _supabase_configured():
        rows = (_supabase().table("users").select("password_salt,password_hash")
                .eq("username", username).limit(1).execute().data)
        row = rows[0] if rows else None
    else:
        with get_connection() as conn:
            found = conn.execute(
                "SELECT password_salt, password_hash FROM users WHERE username=? COLLATE NOCASE",
                (username,),
            ).fetchone()
        row = dict(found) if found else None
    if not row:
        return False
    _, candidate = _hash_password(password, bytes.fromhex(row["password_salt"]))
    return hmac.compare_digest(candidate, row["password_hash"])


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
