import re
import sqlite3
import time
import secrets
import hashlib

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

auth = Blueprint("auth", __name__)

SESSION_SECONDS = 12 * 60 * 60


def connect_db():
    path = current_app.config["MUVI_GO_DB_PATH_GETTER"]()
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            user_id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    return conn


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_user():
    user_id = session.get("user_id")
    token = session.get("auth_token")

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or not isinstance(token, str)
    ):
        return None

    conn = connect_db()
    try:
        now = time.time()

        row = conn.execute("""
            SELECT u.id, u.name, u.email, u.role
            FROM users u
            JOIN auth_sessions s ON s.user_id = u.id
            WHERE u.id = ?
              AND s.token_hash = ?
              AND s.expires_at > ?
        """, (user_id, hash_token(token), now)).fetchone()

        if row is None:
            conn.execute("""
                DELETE FROM auth_sessions
                WHERE user_id = ? AND expires_at <= ?
            """, (user_id, now))
            conn.commit()
            session.clear()

        return row
    finally:
        conn.close()


def establish_session(conn, user_id):
    token = secrets.token_urlsafe(48)
    expiry = time.time() + SESSION_SECONDS

    conn.execute("""
        INSERT INTO auth_sessions (user_id, token_hash, expires_at)
        VALUES (?, ?, ?)
    """, (user_id, hash_token(token), expiry))

    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["auth_token"] = token


@auth.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not all(isinstance(x, str) for x in (name, email, password)):
        return jsonify({
            "ok": False,
            "error": "name_email_password_required"
        }), 400

    name = name.strip()
    email = email.strip().lower()

    if not name or len(name) > 80:
        return jsonify({"ok": False, "error": "invalid_name"}), 400

    if len(email) > 254 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        return jsonify({"ok": False, "error": "invalid_email"}), 400

    if len(password) < 10 or len(password) > 256:
        return jsonify({
            "ok": False,
            "error": "password_length_invalid"
        }), 400

    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        password_hash = generate_password_hash(password)

        cur = conn.execute("""
            INSERT INTO users (name, email, role, password_hash)
            VALUES (?, ?, 'viewer', ?)
        """, (name, email, password_hash))

        user_id = cur.lastrowid
        establish_session(conn, user_id)
        conn.commit()

    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({
            "ok": False,
            "error": "account_already_exists"
        }), 409
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "user": {
            "id": user_id,
            "name": name,
            "email": email,
            "role": "viewer"
        }
    }), 201


@auth.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}

    email = data.get("email")
    password = data.get("password")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({
            "ok": False,
            "error": "email_password_required"
        }), 400

    conn = connect_db()

    try:
        user = conn.execute("""
            SELECT id, name, email, role, password_hash
            FROM users
            WHERE email = ?
        """, (email.strip().lower(),)).fetchone()

        if (
            not user
            or not user["password_hash"]
            or not check_password_hash(user["password_hash"], password)
        ):
            return jsonify({
                "ok": False,
                "error": "invalid_credentials"
            }), 401

        conn.execute("BEGIN IMMEDIATE")

        now = time.time()

        conn.execute("""
            DELETE FROM auth_sessions
            WHERE expires_at <= ?
        """, (now,))

        existing = conn.execute("""
            SELECT token_hash
            FROM auth_sessions
            WHERE user_id = ?
        """, (user["id"],)).fetchone()

        existing_token = session.get("auth_token")

        if existing:
            if (
                isinstance(existing_token, str)
                and hash_token(existing_token) == existing["token_hash"]
            ):
                # Same browser session: renew its expiry.
                conn.execute("""
                    UPDATE auth_sessions
                    SET expires_at = ?
                    WHERE user_id = ?
                """, (now + SESSION_SECONDS, user["id"]))

                session.permanent = True
                conn.commit()

                return jsonify({
                    "ok": True,
                    "user": {
                        "id": user["id"],
                        "name": user["name"],
                        "email": user["email"],
                        "role": user["role"]
                    }
                })

            conn.rollback()
            return jsonify({
                "ok": False,
                "error": "account currently in use"
            }), 409

        public_user = {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"]
        }

        establish_session(conn, user["id"])
        conn.commit()

    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "user": public_user
    })


@auth.post("/api/auth/logout")
def logout():
    user_id = session.get("user_id")
    token = session.get("auth_token")

    if (
        isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and isinstance(token, str)
    ):
        conn = connect_db()
        try:
            conn.execute("""
                DELETE FROM auth_sessions
                WHERE user_id = ? AND token_hash = ?
            """, (user_id, hash_token(token)))
            conn.commit()
        finally:
            conn.close()

    session.clear()
    return jsonify({"ok": True})


@auth.get("/api/auth/me")
def me():
    user = current_user()

    if user is None:
        session.clear()
        return jsonify({
            "ok": True,
            "authenticated": False,
            "user": None
        })

    return jsonify({
        "ok": True,
        "authenticated": True,
        "user": dict(user)
    })
