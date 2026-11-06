import re
import sqlite3

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

auth = Blueprint("auth", __name__)


def connect_db():
    path = current_app.config["MUVI_GO_DB_PATH_GETTER"]()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def current_user():
    user_id = session.get("user_id")
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        return None

    conn = connect_db()
    try:
        return conn.execute(
            "SELECT id, name, email, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


@auth.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not all(isinstance(x, str) for x in (name, email, password)):
        return jsonify({"ok": False, "error": "name_email_password_required"}), 400

    name = name.strip()
    email = email.strip().lower()

    if not name or len(name) > 80:
        return jsonify({"ok": False, "error": "invalid_name"}), 400

    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({"ok": False, "error": "invalid_email"}), 400

    if len(password) < 10 or len(password) > 256:
        return jsonify({"ok": False, "error": "password_length_invalid"}), 400

    conn = connect_db()
    try:
        exists = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if exists:
            return jsonify({"ok": False, "error": "account_already_exists"}), 409

        password_hash = generate_password_hash(password)
        cur = conn.execute(
            """INSERT INTO users (name, email, role, password_hash)
               VALUES (?, ?, 'viewer', ?)""",
            (name, email, password_hash),
        )
        conn.commit()
        user_id = cur.lastrowid
    finally:
        conn.close()

    session.clear()
    session["user_id"] = user_id
    return jsonify({
        "ok": True,
        "user": {"id": user_id, "name": name, "email": email, "role": "viewer"},
    }), 201


@auth.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"ok": False, "error": "email_password_required"}), 400

    conn = connect_db()
    try:
        user = conn.execute(
            """SELECT id, name, email, role, password_hash
               FROM users WHERE email = ?""",
            (email.strip().lower(),),
        ).fetchone()

        if not user or not user["password_hash"] or not check_password_hash(
            user["password_hash"], password
        ):
            return jsonify({"ok": False, "error": "invalid_credentials"}), 401

        public_user = {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        }
    finally:
        conn.close()

    session.clear()
    session["user_id"] = public_user["id"]
    return jsonify({"ok": True, "user": public_user})


@auth.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth.get("/api/auth/me")
def me():
    user = current_user()
    if user is None:
        session.clear()
        return jsonify({"ok": True, "authenticated": False, "user": None})

    return jsonify({
        "ok": True,
        "authenticated": True,
        "user": dict(user),
    })
