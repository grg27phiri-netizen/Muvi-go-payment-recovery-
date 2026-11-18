"""MUVI GO Live TV administrator channel management.

Authorization and feed verification are explicit administrator decisions.
This module does not fetch or probe third-party stream URLs.
"""

import ipaddress
import json
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request
from auth import current_user


live_tv_admin_bp = Blueprint("live_tv_admin", __name__)

CHANNEL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")

AUTHORIZATION_STATUSES = {"pending", "authorized", "rejected"}
FEED_STATUSES = {"not_verified", "verified", "error"}

TEXT_LIMITS = {
    "name": 100,
    "category": 60,
    "icon": 16,
    "rights_holder": 160,
    "authorization_reference": 500,
    "authorization_notes": 2000,
}


def init_live_tv_schema(conn):
    """Apply safe, repeatable additions to the existing live_channels table."""

    migrations = {
        "rights_holder": "TEXT",
        "authorization_reference": "TEXT",
        "authorization_notes": "TEXT",
        "authorization_checked_at": "TEXT",
        "authorization_checked_by": "INTEGER",
        "feed_checked_at": "TEXT",
        "feed_checked_by": "INTEGER",
        "created_by": "INTEGER",
        "updated_by": "INTEGER",
    }

    existing = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(live_channels)"
        ).fetchall()
    }

    for column, definition in migrations.items():
        if column not in existing:
            conn.execute(
                "ALTER TABLE live_channels ADD COLUMN "
                + column + " " + definition
            )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS live_channel_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_db_id INTEGER NOT NULL,
            actor_user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_channel_audit_channel
        ON live_channel_audit(channel_db_id, id)
    """)


def _db():
    # Import at request time to avoid an application-import cycle.
    from app import db
    return db()


def _error(code, status):
    return jsonify({"ok": False, "error": code}), status


def _admin_guard():
    user = current_user()

    if user is None:
        return None, _error("login_required", 401)

    if user["role"] != "admin":
        return None, _error("admin_only", 403)

    return user, None


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _audit(conn, channel_db_id, actor_id, action, details):
    conn.execute(
        """
        INSERT INTO live_channel_audit
        (channel_db_id, actor_user_id, action, details)
        VALUES (?, ?, ?, ?)
        """,
        (
            channel_db_id,
            actor_id,
            action,
            json.dumps(details, ensure_ascii=False),
        ),
    )


def _valid_stream_url(value):
    """Accept only public HTTPS HLS playlist URLs.

    This validates URL syntax only. It does not prove that the feed works
    or that MUVI GO has broadcasting rights.
    """

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or value != value.strip()
        or any(char.isspace() for char in value)
    ):
        return False

    try:
        parsed = urlsplit(value)
        host = parsed.hostname

        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.lower().endswith(".m3u8")
            or parsed.fragment
        ):
            return False

        # Reject malformed ports.
        _ = parsed.port

        normal_host = host.lower().rstrip(".")

        if (
            normal_host == "localhost"
            or normal_host.endswith(".localhost")
        ):
            return False

        # If the host is an IP address, require a globally routable address.
        try:
            address = ipaddress.ip_address(normal_host)
            if not address.is_global:
                return False
        except ValueError:
            # A hostname rather than an IP address.
            pass

        return True

    except ValueError:
        return False


def _channel_dict(row):
    return dict(row)


@live_tv_admin_bp.route(
    "/api/admin/channels",
    methods=["GET"]
)
def admin_list_channels():
    user, error = _admin_guard()
    if error:
        return error

    conn = _db()
    try:
        rows = conn.execute("""
            SELECT *
            FROM live_channels
            ORDER BY category COLLATE NOCASE, name COLLATE NOCASE, id
        """).fetchall()

        response = jsonify({
            "ok": True,
            "channels": [_channel_dict(row) for row in rows],
        })
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        conn.close()



@live_tv_admin_bp.route(
    "/api/admin/live-tv/audit",
    methods=["GET"]
)
def admin_live_tv_audit():
    user, error = _admin_guard()
    if error:
        return error

    conn = _db()
    try:
        rows = conn.execute("""
            SELECT id, channel_db_id, actor_user_id,
                   action, details, created_at
            FROM live_channel_audit
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

        response = jsonify({
            "ok": True,
            "events": [dict(row) for row in rows],
        })
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        conn.close()


@live_tv_admin_bp.route(
    "/api/admin/channels",
    methods=["POST"]
)
def admin_create_channel():
    user, error = _admin_guard()
    if error:
        return error

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("invalid_json", 400)

    channel_id = data.get("channel_id")
    name = data.get("name")
    category = data.get("category")
    icon = data.get("icon", "📺")

    if (
        not isinstance(channel_id, str)
        or not CHANNEL_ID_PATTERN.fullmatch(channel_id)
    ):
        return _error("invalid_channel_id", 400)

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        return _error("invalid_name", 400)

    if (
        not isinstance(category, str)
        or not category.strip()
        or len(category.strip()) > 60
    ):
        return _error("invalid_category", 400)

    if not isinstance(icon, str) or len(icon.strip()) > 16:
        return _error("invalid_icon", 400)

    conn = _db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO live_channels (
                channel_id,
                name,
                category,
                icon,
                authorization_status,
                feed_status,
                is_active,
                created_by,
                updated_by
            )
            VALUES (?, ?, ?, ?, 'pending', 'not_verified', 0, ?, ?)
            """,
            (
                channel_id.lower(),
                name.strip(),
                category.strip(),
                icon.strip() or "📺",
                user["id"],
                user["id"],
            ),
        )

        channel_pk = cursor.lastrowid

        _audit(
            conn,
            channel_pk,
            user["id"],
            "channel_created",
            {
                "channel_id": channel_id.lower(),
                "authorization_status": "pending",
                "feed_status": "not_verified",
                "is_active": 0,
            },
        )

        conn.commit()

        return jsonify({
            "ok": True,
            "channel_db_id": channel_pk,
            "authorization_status": "pending",
            "feed_status": "not_verified",
            "is_active": False,
        }), 201

    except sqlite3.IntegrityError:
        conn.rollback()
        return _error("channel_id_already_exists", 409)

    finally:
        conn.close()


@live_tv_admin_bp.route(
    "/api/admin/channels/<int:channel_pk>",
    methods=["PATCH"]
)
def admin_update_channel(channel_pk):
    user, error = _admin_guard()
    if error:
        return error

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("invalid_json", 400)

    allowed_fields = (
        set(TEXT_LIMITS)
        | {
            "stream_url",
            "authorization_status",
            "feed_status",
            "is_active",
        }
    )

    unknown = set(data) - allowed_fields
    if unknown:
        return _error("unknown_channel_field", 400)

    if not data:
        return _error("no_channel_changes", 400)

    conn = _db()

    try:
        row = conn.execute(
            "SELECT * FROM live_channels WHERE id = ?",
            (channel_pk,),
        ).fetchone()

        if row is None:
            return _error("channel_not_found", 404)

        before = dict(row)
        state = dict(before)
        supplied = {}

        for field, maximum in TEXT_LIMITS.items():
            if field not in data:
                continue

            value = data[field]

            if not isinstance(value, str):
                return _error("invalid_" + field, 400)

            value = value.strip()

            if len(value) > maximum:
                return _error(field + "_too_long", 400)

            if field in {"name", "category"} and not value:
                return _error("invalid_" + field, 400)

            state[field] = value or None
            supplied[field] = state[field]

        if "stream_url" in data:
            value = data["stream_url"]

            if value is None or value == "":
                state["stream_url"] = None
            elif not _valid_stream_url(value):
                return _error("invalid_https_hls_url", 400)
            else:
                state["stream_url"] = value

            supplied["stream_url"] = state["stream_url"]

        if "authorization_status" in data:
            value = data["authorization_status"]

            if (
                not isinstance(value, str)
                or value not in AUTHORIZATION_STATUSES
            ):
                return _error("invalid_authorization_status", 400)

            state["authorization_status"] = value
            supplied["authorization_status"] = value

        if "feed_status" in data:
            value = data["feed_status"]

            if (
                not isinstance(value, str)
                or value not in FEED_STATUSES
            ):
                return _error("invalid_feed_status", 400)

            state["feed_status"] = value
            supplied["feed_status"] = value

        if "is_active" in data:
            value = data["is_active"]

            if isinstance(value, bool):
                value = int(value)
            elif type(value) is not int or value not in (0, 1):
                return _error("invalid_active_value", 400)

            state["is_active"] = value
            supplied["is_active"] = value

        rights_fields = {
            "rights_holder",
            "authorization_reference",
            "authorization_notes",
        }

        rights_changed = any(
            field in supplied and supplied[field] != before.get(field)
            for field in rights_fields
        )

        stream_changed = (
            "stream_url" in supplied
            and supplied["stream_url"] != before.get("stream_url")
        )

        # Any change to the rights record requires a fresh authorization review.
        if rights_changed:
            state["authorization_status"] = "pending"
            state["authorization_checked_at"] = None
            state["authorization_checked_by"] = None
            state["feed_status"] = "not_verified"
            state["feed_checked_at"] = None
            state["feed_checked_by"] = None
            state["is_active"] = 0

        # A changed stream URL must be checked again before it can be used.
        if stream_changed:
            state["feed_status"] = "not_verified"
            state["feed_checked_at"] = None
            state["feed_checked_by"] = None
            state["is_active"] = 0

        # An unapproved or rejected channel cannot retain a verified active feed.
        if state["authorization_status"] != "authorized":
            state["feed_status"] = "not_verified"
            state["is_active"] = 0

        if (
            state["authorization_status"] == "authorized"
            and (
                not state.get("rights_holder")
                or not state.get("authorization_reference")
            )
        ):
            return _error("authorization_evidence_required", 409)

        if state["feed_status"] == "verified":
            if state["authorization_status"] != "authorized":
                return _error("channel_not_authorized", 409)

            if not _valid_stream_url(state.get("stream_url")):
                return _error("verified_stream_url_required", 409)

        if state["is_active"] == 1:
            if not (
                state["authorization_status"] == "authorized"
                and state["feed_status"] == "verified"
                and _valid_stream_url(state.get("stream_url"))
            ):
                return _error("channel_not_ready", 409)

        now = _now()

        if rights_changed:
            state["authorization_checked_at"] = None
            state["authorization_checked_by"] = None
        elif (
            "authorization_status" in supplied
            and supplied["authorization_status"] != before["authorization_status"]
        ):
            state["authorization_checked_at"] = now
            state["authorization_checked_by"] = user["id"]

        if stream_changed:
            state["feed_checked_at"] = None
            state["feed_checked_by"] = None
        elif (
            "feed_status" in supplied
            and supplied["feed_status"] != before["feed_status"]
        ):
            if state["feed_status"] in {"verified", "error"}:
                state["feed_checked_at"] = now
                state["feed_checked_by"] = user["id"]
            else:
                state["feed_checked_at"] = None
                state["feed_checked_by"] = None

        state["updated_by"] = user["id"]

        columns = [
            "name",
            "category",
            "icon",
            "stream_url",
            "rights_holder",
            "authorization_reference",
            "authorization_notes",
            "authorization_status",
            "feed_status",
            "is_active",
            "authorization_checked_at",
            "authorization_checked_by",
            "feed_checked_at",
            "feed_checked_by",
            "updated_by",
        ]

        assignments = ", ".join(
            column + " = ?" for column in columns
        )
        values = [state.get(column) for column in columns]
        values.extend([now, channel_pk])

        conn.execute(
            "UPDATE live_channels SET "
            + assignments
            + ", updated_at = ? WHERE id = ?",
            values,
        )

        _audit(
            conn,
            channel_pk,
            user["id"],
            "channel_updated",
            {
                "authorization_status": state["authorization_status"],
                "feed_status": state["feed_status"],
                "is_active": state["is_active"],
                "rights_record_changed": rights_changed,
                "stream_url_changed": stream_changed,
            },
        )

        conn.commit()

        updated = conn.execute(
            "SELECT * FROM live_channels WHERE id = ?",
            (channel_pk,),
        ).fetchone()

        return jsonify({
            "ok": True,
            "channel": _channel_dict(updated),
        })

    finally:
        conn.close()


@live_tv_admin_bp.route(
    "/api/admin/channels/<int:channel_pk>",
    methods=["DELETE"]
)
def admin_delete_channel(channel_pk):
    user, error = _admin_guard()
    if error:
        return error

    conn = _db()
    try:
        row = conn.execute(
            "SELECT channel_id FROM live_channels WHERE id = ?",
            (channel_pk,),
        ).fetchone()

        if row is None:
            return _error("channel_not_found", 404)

        _audit(
            conn,
            channel_pk,
            user["id"],
            "channel_deleted",
            {"channel_id": row["channel_id"]},
        )

        conn.execute(
            "DELETE FROM live_channels WHERE id = ?",
            (channel_pk,),
        )
        conn.commit()

        return jsonify({
            "ok": True,
            "deleted_id": channel_pk,
        })

    finally:
        conn.close()
