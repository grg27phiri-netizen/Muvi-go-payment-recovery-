from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
import sqlite3, os
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "muvi_go.db"
app = Flask(__name__)
app.config["DATABASE_PATH"] = str(DB)
app.config["MUVI_GO_DB_PATH_GETTER"] = (
    lambda: app.config.get("DATABASE_PATH", str(DB))
)
# Load persistent MUVI GO environment settings.
_env_file = BASE / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _value = _line.partition("=")
            os.environ.setdefault(
                _key.strip(),
                _value.strip().strip('"').strip("'")
            )

app.secret_key = os.environ["SECRET_KEY"]

from payments import payments_bp
from auth import auth as auth_bp, current_user
from live_tv_admin import live_tv_admin_bp, init_live_tv_schema, _valid_stream_url

app.register_blueprint(payments_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(live_tv_admin_bp)

def db():
    database_path = Path(app.config.get("DATABASE_PATH", str(DB)))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(database_path)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS media (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      type TEXT NOT NULL,
      category TEXT DEFAULT 'Zambian Content',
      description TEXT DEFAULT '',
      status TEXT DEFAULT 'PUBLISHED',
      year INTEGER DEFAULT 2026,
      views INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT UNIQUE,
      role TEXT DEFAULT 'viewer'
    );
    CREATE TABLE IF NOT EXISTS payments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      payment_ref TEXT NOT NULL UNIQUE,
      user_id INTEGER NOT NULL,
      provider TEXT NOT NULL CHECK(provider IN ('mtn_momo','airtel_money')),
      plan TEXT NOT NULL CHECK(plan IN ('weekly','monthly','annual')),
      amount INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','successful','failed','cancelled')),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      verified_at TEXT
    );
    CREATE TABLE IF NOT EXISTS subscriptions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      payment_ref TEXT NOT NULL UNIQUE,
      plan TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # MUVI GO Live TV V1: repeatable channel migration.
    c.execute("""
        CREATE TABLE IF NOT EXISTS live_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            stream_url TEXT,
            stream_type TEXT NOT NULL DEFAULT 'hls',
            authorization_status TEXT NOT NULL DEFAULT 'pending'
                CHECK(authorization_status IN
                    ('pending', 'authorized', 'rejected')),
            feed_status TEXT NOT NULL DEFAULT 'not_verified'
                CHECK(feed_status IN
                    ('not_verified', 'verified', 'error')),
            is_active INTEGER NOT NULL DEFAULT 0
                CHECK(is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_channels_active
        ON live_channels(is_active, category)
    """)


    # MUVI GO Live TV: safely import the existing channel catalogue.
    channel_columns = {
        row[1] for row in c.execute(
            "PRAGMA table_info(live_channels)"
        ).fetchall()
    }
    if "icon" not in channel_columns:
        c.execute(
            "ALTER TABLE live_channels ADD COLUMN icon TEXT NOT NULL DEFAULT '📺'"
        )

    # MUVI GO Live TV administrator metadata and audit migration.
    init_live_tv_schema(c)

    import re
    js_path = BASE / "static" / "app.js"
    if js_path.exists():
        js = js_path.read_text(encoding="utf-8")
        match = re.search(
            r"const\s+channels\s*=\s*\[(.*?)\n\];",
            js,
            re.S
        )
        if match:
            pattern = re.compile(
                r'makeChannel\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,'
                r'\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)'
            )
            for name, category, channel_id, icon in pattern.findall(match.group(1)):
                c.execute("""
                    INSERT OR IGNORE INTO live_channels
                    (channel_id, name, category, icon,
                     authorization_status, feed_status, is_active)
                    VALUES (?, ?, ?, ?, 'pending', 'not_verified', 0)
                """, (channel_id, name, category, icon))

    # Safe, repeatable migration for authentication.
    user_columns = {
        row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()
    }
    if "password_hash" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    # Safe schema migration for payment-confirmation idempotency.
    payment_columns = {
        row[1] for row in c.execute("PRAGMA table_info(payments)").fetchall()
    }
    if "provider_transaction_id" not in payment_columns:
        c.execute("ALTER TABLE payments ADD COLUMN provider_transaction_id TEXT")
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_provider_transaction
        ON payments(provider, provider_transaction_id)
        WHERE provider_transaction_id IS NOT NULL
    """)

    # Safe, repeatable subscription-expiry migration.
    subscription_columns = {
        row[1] for row in c.execute(
            "PRAGMA table_info(subscriptions)"
        ).fetchall()
    }
    if "expires_at" not in subscription_columns:
        c.execute("ALTER TABLE subscriptions ADD COLUMN expires_at TEXT")

    # Backfill old subscriptions using their original creation date.
    c.execute("""
        UPDATE subscriptions
        SET expires_at = datetime(
            created_at,
            CASE plan
                WHEN 'weekly' THEN '+7 days'
                WHEN 'monthly' THEN '+30 days'
                WHEN 'annual' THEN '+365 days'
            END
        )
        WHERE expires_at IS NULL
          AND plan IN ('weekly', 'monthly', 'annual')
    """)

    # Keep upload metadata available even before the first upload.
    media_columns = {
        row[1] for row in c.execute("PRAGMA table_info(media)").fetchall()
    }
    media_migrations = {
        "file_path": "TEXT",
        "original_filename": "TEXT",
        "mime_type": "TEXT",
        "file_size": "INTEGER",
    }
    for column, definition in media_migrations.items():
        if column not in media_columns:
            c.execute(
                "ALTER TABLE media ADD COLUMN " + column + " " + definition
            )

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_status_file_path
        ON media(status, file_path)
    """)

    if c.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0:
        seed=[
          ("MUVI GO Welcome","movie","Zambian Content","Welcome to MUVI GO","PUBLISHED",2026,120),
          ("Zambian Stories","documentary","Zambian Content","Stories, people and places from Zambia","PUBLISHED",2026,86),
          ("MUVI GO Music Sessions","music","Music","Local music discovery","PUBLISHED",2026,54),
          ("Africa World","series","Series","A collection of African stories","PUBLISHED",2026,41)
        ]
        c.executemany("INSERT INTO media(title,type,category,description,status,year,views) VALUES(?,?,?,?,?,?,?)",seed)
    c.commit(); c.close()

@app.route("/")
def home():
    c=db()
    media=c.execute("SELECT * FROM media WHERE status='PUBLISHED' ORDER BY id DESC").fetchall()
    c.close()
    return render_template("index.html", media=media)

@app.route("/media-test.mp4")
def media_test_video():
    """Serve the local demo video only to subscribed authenticated users."""
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401

    conn = db()
    try:
        subscription = conn.execute(
            """
            SELECT 1
            FROM subscriptions
            WHERE user_id = ?
              AND status = 'active'
              AND expires_at > CURRENT_TIMESTAMP
            LIMIT 1
            """,
            (user["id"],),
        ).fetchone()
    finally:
        conn.close()

    if subscription is None:
        return jsonify({
            "ok": False,
            "error": "active_subscription_required"
        }), 403

    test_filename = "muvi-test-h264.mp4"
    safe_target = _muvi_safe_media_target("videos", test_filename)

    if safe_target is None:
        return jsonify({"ok": False, "error": "test_video_not_found"}), 404

    folder, _ = safe_target
    response = send_from_directory(
        str(folder),
        test_filename,
        mimetype="video/mp4",
        conditional=True,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
    return response

@app.route("/api/channels")
def channels_api():
    """Return the SQLite channel catalogue without exposing unapproved feeds."""
    c = db()
    try:
        rows = c.execute("""
            SELECT channel_id, name, category, icon, stream_url,
                   stream_type, authorization_status, feed_status, is_active,
                   feed_verification_method, feed_verification_notes
            FROM live_channels
            ORDER BY id
        """).fetchall()
    finally:
        c.close()

    channels = []
    for row in rows:
        url = row["stream_url"]
        playable = (
            row["authorization_status"] == "authorized"
            and row["feed_status"] == "verified"
            and row["feed_verification_method"] == "manual_playback"
            and bool(row["feed_verification_notes"])
            and row["is_active"] == 1
            and row["stream_type"] == "hls"
            and _valid_stream_url(url)
        )

        channels.append({
            "id": row["channel_id"],
            "name": row["name"],
            "category": row["category"],
            "icon": row["icon"] or "📺",
            "feed_status": row["feed_status"],
            "available": playable,
            "stream_url": url if playable else None
        })

    response = jsonify(channels)
    response.headers["Cache-Control"] = "no-store"
    return response


def _muvi_safe_media_target(kind, filename):
    """Resolve a media file while rejecting traversal and symlink escapes."""
    allowed = {
        "videos": {".mp4", ".webm", ".m4v", ".mov"},
        "music": {".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac", ".opus"},
    }

    if (
        kind not in allowed
        or not isinstance(filename, str)
        or not filename
    ):
        return None

    folder = (BASE / "media" / kind).resolve()
    original_target = folder / filename

    try:
        if original_target.is_symlink():
            return None

        target = original_target.resolve(strict=True)
        target.relative_to(folder)
    except (OSError, RuntimeError, ValueError):
        return None

    if not target.is_file() or target.suffix.lower() not in allowed[kind]:
        return None

    return folder, target


@app.route("/api/library")
def media_library_api():
    """List only existing files whose database records are PUBLISHED."""
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401

    conn = db()
    try:
        records = conn.execute(
            """
            SELECT title, type, file_path
            FROM media
            WHERE status = 'PUBLISHED'
              AND file_path IS NOT NULL
              AND TRIM(file_path) != ''
            ORDER BY id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    items = []

    for record in records:
        relative_path = record["file_path"]

        if not isinstance(relative_path, str):
            continue

        parts = relative_path.split("/")
        if len(parts) != 2:
            continue

        kind, filename = parts

        if kind not in {"videos", "music"}:
            continue

        media_type = record["type"]

        if kind == "music" and media_type != "music":
            continue

        if kind == "videos" and media_type not in {
            "movie", "series", "documentary"
        }:
            continue

        if _muvi_safe_media_target(kind, filename) is None:
            continue

        items.append({
            "title": record["title"],
            "type": "music" if kind == "music" else "video",
            "filename": filename,
            "url": "/media-files/" + kind + "/" + quote(filename),
        })

    return jsonify(items)

@app.route("/media-files/<kind>/<path:filename>")
def serve_media_file(kind, filename):
    """Serve published premium videos and authenticated free music."""
    if kind not in {"videos", "music"}:
        return jsonify({"error": "unsupported media folder"}), 404

    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401

    safe_target = _muvi_safe_media_target(kind, filename)
    if safe_target is None:
        return jsonify({"error": "media file not found"}), 404

    folder, _ = safe_target
    relative_path = kind + "/" + filename

    conn = db()
    try:
        media_record = conn.execute(
            """
            SELECT type
            FROM media
            WHERE file_path = ?
              AND status = 'PUBLISHED'
            LIMIT 1
            """,
            (relative_path,),
        ).fetchone()
    finally:
        conn.close()

    if media_record is None:
        return jsonify({"error": "media file not found"}), 404

    if kind == "music" and media_record["type"] != "music":
        return jsonify({"error": "media file not found"}), 404

    if kind == "videos" and media_record["type"] not in {
        "movie", "series", "documentary"
    }:
        return jsonify({"error": "media file not found"}), 404

    # Every video requires an active, unexpired subscription.
    # Authenticated music remains free.
    if kind == "videos":
        conn = db()
        try:
            subscription = conn.execute(
                """
                SELECT 1
                FROM subscriptions
                WHERE user_id = ?
                  AND status = 'active'
                  AND expires_at > CURRENT_TIMESTAMP
                LIMIT 1
                """,
                (user["id"],),
            ).fetchone()
        finally:
            conn.close()

        if subscription is None:
            return jsonify({
                "ok": False,
                "error": "active_subscription_required"
            }), 403

    response = send_from_directory(
        str(folder),
        filename,
        conditional=True,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
    return response

@app.route("/sw.js")
def service_worker():
    response = make_response(send_from_directory(BASE / "static", "sw.js"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response

@app.route("/admin")
def admin():
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if user["role"] != "admin":
        return jsonify({"ok": False, "error": "admin_only"}), 403
    c=db()
    media=c.execute("SELECT * FROM media ORDER BY id DESC").fetchall()
    c.close()
    return render_template("admin.html", media=media)

@app.route("/account")
def viewer_account():
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if user["role"] == "admin":
        return make_response("", 302, {"Location": "/admin"})
    c = db()
    subscription = c.execute("""
        SELECT plan, status, created_at, expires_at,
               CASE
                   WHEN status = 'active'
                    AND expires_at > CURRENT_TIMESTAMP
                   THEN 1 ELSE 0
               END AS is_active
        FROM subscriptions
        WHERE user_id = ?
        ORDER BY is_active DESC, expires_at DESC
        LIMIT 1
    """, (user["id"],)).fetchone()
    c.close()

    # The main MUVI GO dashboard is the canonical viewer dashboard.
    return make_response("", 302, {"Location": "/"})


@app.route("/api/search")
def search():
    q=request.args.get("q","").strip()
    c=db()
    rows=c.execute("""SELECT * FROM media WHERE status='PUBLISHED'
                      AND (title LIKE ? OR category LIKE ? OR description LIKE ?)
                      ORDER BY views DESC""",(f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    c.close()
    return jsonify([dict(x) for x in rows])


@app.route("/api/media", methods=["POST"])
def add_media():
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if user["role"] != "admin":
        return jsonify({"ok": False, "error": "admin_only"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    title = str(data.get("title", "")).strip()
    typ = str(data.get("type", "movie")).strip().lower()
    category = str(data.get("category", "Zambian Content")).strip() or "Zambian Content"
    desc = str(data.get("description", "")).strip()

    allowed_types = {"movie", "series", "music", "documentary"}

    if not title or len(title) > 200:
        return jsonify({"ok": False, "error": "invalid_title"}), 400
    if typ not in allowed_types:
        return jsonify({"ok": False, "error": "unsupported_media_type"}), 400
    if len(category) > 100 or len(desc) > 2000:
        return jsonify({"ok": False, "error": "field_too_long"}), 400

    c = db()
    try:
        c.execute(
            """INSERT INTO media
            (title,type,category,description,status,year)
            VALUES(?,?,?,?,?,?)""",
            (title, typ, category, desc, "PENDING", 2026)
        )
        c.commit()
        return jsonify({"ok": True}), 200
    finally:
        c.close()


@app.route("/api/media/<int:media_id>", methods=["PATCH"])
def update_media(media_id):
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if user["role"] != "admin":
        return jsonify({"ok": False, "error": "admin_only"}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    allowed_types = {"movie", "series", "music", "documentary"}
    allowed_statuses = {
        "PUBLISHED", "PENDING", "INACTIVE",
        "RIGHTS_CHECK", "CONTENT_NEEDED", "VOD_PENDING"
    }

    fields = {}
    if "title" in data:
        value = data["title"]
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
            return jsonify({"ok": False, "error": "invalid_title"}), 400
        fields["title"] = value.strip()

    if "type" in data:
        value = data["type"]
        if not isinstance(value, str) or value.strip().lower() not in allowed_types:
            return jsonify({"ok": False, "error": "unsupported_media_type"}), 400
        fields["type"] = value.strip().lower()

    if "category" in data:
        value = data["category"]
        if not isinstance(value, str) or len(value.strip()) > 100:
            return jsonify({"ok": False, "error": "invalid_category"}), 400
        fields["category"] = value.strip() or "Zambian Content"

    if "description" in data:
        value = data["description"]
        if not isinstance(value, str) or len(value.strip()) > 2000:
            return jsonify({"ok": False, "error": "invalid_description"}), 400
        fields["description"] = value.strip()

    if "status" in data:
        value = data["status"]
        if not isinstance(value, str) or value.strip().upper() not in allowed_statuses:
            return jsonify({"ok": False, "error": "invalid_status"}), 400
        fields["status"] = value.strip().upper()

    if not fields:
        return jsonify({"ok": False, "error": "no_valid_fields"}), 400

    c = db()
    try:
        existing = c.execute(
            "SELECT id FROM media WHERE id=?", (media_id,)
        ).fetchone()

        if existing is None:
            return jsonify({"ok": False, "error": "media_not_found"}), 404

        columns = list(fields.keys())
        assignments = ", ".join(f"{column}=?" for column in columns)
        values = [fields[column] for column in columns]

        c.execute(
            f"UPDATE media SET {assignments} WHERE id=?",
            values + [media_id]
        )
        c.commit()
        return jsonify({"ok": True, "id": media_id})
    finally:
        c.close()


@app.route("/api/media/<int:media_id>", methods=["DELETE"])
def delete_media(media_id):
    user = current_user()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if user["role"] != "admin":
        return jsonify({"ok": False, "error": "admin_only"}), 403

    c = db()
    try:
        result = c.execute(
            "DELETE FROM media WHERE id=?", (media_id,)
        )
        if result.rowcount != 1:
            c.rollback()
            return jsonify({"ok": False, "error": "media_not_found"}), 404

        c.commit()
        return jsonify({"ok": True, "deleted_id": media_id})
    finally:
        c.close()


@app.route("/api/health")
def health():
    return jsonify({"service":"MUVI GO","status":"online","version":"6.0-android-preparation"})

# ===== MUVI GO V6 SECURITY FOUNDATION =====
import os as _v6_os
from datetime import timedelta as _v6_timedelta
from urllib.parse import urlsplit as _v6_urlsplit
from flask import request as _v6_request, jsonify as _v6_jsonify

# Secure browser session defaults.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        _v6_os.environ.get("MUVI_GO_COOKIE_SECURE", "0") == "1"
    ),
    SESSION_REFRESH_EACH_REQUEST=False,
    PERMANENT_SESSION_LIFETIME=_v6_timedelta(hours=12),
)

# Protect unsafe API requests against cross-origin browser submissions.
@app.before_request
def muvi_go_v6_origin_protection():
    if _v6_request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    if not _v6_request.path.startswith("/api/"):
        return None

    fetch_site = _v6_request.headers.get("Sec-Fetch-Site", "").lower()

    if fetch_site == "cross-site":
        return _v6_jsonify({
            "ok": False,
            "error": "cross_origin_request_blocked"
        }), 403

    origin = _v6_request.headers.get("Origin")

    if origin:
        try:
            parsed = _v6_urlsplit(origin)

            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.netloc.lower() != _v6_request.host.lower()
            ):
                return _v6_jsonify({
                    "ok": False,
                    "error": "invalid_request_origin"
                }), 403

        except ValueError:
            return _v6_jsonify({
                "ok": False,
                "error": "invalid_request_origin"
            }), 403

    return None


# Apply security headers to application responses.
@app.after_request
def muvi_go_v6_security_headers(response):

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"

    if (
        _v6_request.path.startswith("/api/")
        or _v6_request.path in {"/admin", "/account"}
    ):
        response.headers["Cache-Control"] = "no-store"

    if _v6_request.is_secure:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000"
        )

    return response

# ===== END MUVI GO V6 SECURITY FOUNDATION =====



# ===== MUVI GO SECURE MEDIA UPLOAD V1 =====

import os as _upload_os
import uuid as _upload_uuid
import mimetypes as _upload_mimetypes
from pathlib import Path as _UploadPath
from datetime import datetime as _UploadDate
from werkzeug.utils import secure_filename as _upload_secure_filename

# Maximum HTTP request size: 2 GB.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024


def _muvi_upload_valid_header(header, extension):
    """Validate file signatures, not just user-supplied extensions."""

    if extension in {".mp4", ".m4v", ".mov", ".m4a"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"

    if extension == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")

    if extension == ".mp3":
        return (
            header.startswith(b"ID3")
            or (
                len(header) >= 2
                and header[0] == 0xFF
                and (header[1] & 0xE0) == 0xE0
            )
        )

    if extension == ".aac":
        return (
            len(header) >= 2
            and header[0] == 0xFF
            and (header[1] & 0xF6) == 0xF0
        )

    if extension in {".ogg", ".opus"}:
        return header.startswith(b"OggS")

    if extension == ".wav":
        return (
            header.startswith(b"RIFF")
            and header[8:12] == b"WAVE"
        )

    if extension == ".flac":
        return header.startswith(b"fLaC")

    return False


@app.route("/api/media/upload", methods=["POST"])
def muvi_upload_media():

    user = current_user()

    if user is None:
        return jsonify({
            "ok": False,
            "error": "login_required"
        }), 401

    if user["role"] != "admin":
        return jsonify({
            "ok": False,
            "error": "admin_only"
        }), 403

    media_file = request.files.get("media_file")

    if media_file is None or not media_file.filename:
        return jsonify({
            "ok": False,
            "error": "please_select_a_file"
        }), 400

    title = request.form.get("title", "").strip()
    typ = request.form.get("type", "movie").strip().lower()
    category = (
        request.form.get("category", "Zambian Content").strip()
        or "Zambian Content"
    )
    description = request.form.get("description", "").strip()

    if not title or len(title) > 200:
        return jsonify({
            "ok": False,
            "error": "invalid_title"
        }), 400

    if typ not in {"movie", "series", "music", "documentary"}:
        return jsonify({
            "ok": False,
            "error": "unsupported_media_type"
        }), 400

    if len(category) > 100 or len(description) > 2000:
        return jsonify({
            "ok": False,
            "error": "field_too_long"
        }), 400

    original_name = _upload_secure_filename(media_file.filename)

    if not original_name:
        return jsonify({
            "ok": False,
            "error": "invalid_filename"
        }), 400

    extension = _UploadPath(original_name).suffix.lower()

    allowed = {
        "videos": {".mp4", ".webm", ".m4v", ".mov"},
        "music": {
            ".mp3", ".m4a", ".aac", ".ogg",
            ".wav", ".flac", ".opus"
        }
    }

    kind = "music" if typ == "music" else "videos"

    if extension not in allowed[kind]:
        return jsonify({
            "ok": False,
            "error": "file_extension_not_allowed"
        }), 400

    # Check the actual file signature.
    try:
        header = media_file.stream.read(64)
        media_file.stream.seek(0)
    except Exception:
        return jsonify({
            "ok": False,
            "error": "unable_to_read_upload"
        }), 400

    if not _muvi_upload_valid_header(header, extension):
        return jsonify({
            "ok": False,
            "error": "file_content_does_not_match_extension"
        }), 400

    folder = (_UploadPath(BASE) / "media" / kind).resolve()
    folder.mkdir(parents=True, exist_ok=True)

    # UUID filenames prevent collisions and path traversal.
    stored_name = _upload_uuid.uuid4().hex + extension

    final_path = folder / stored_name
    temp_path = folder / ("." + stored_name + ".uploading")

    saved_path = None
    conn = None

    try:
        media_file.save(str(temp_path))

        file_size = temp_path.stat().st_size

        if file_size <= 0:
            raise ValueError("empty_file")

        if file_size > 2 * 1024 * 1024 * 1024:
            raise ValueError("file_too_large")

        # Atomic move into final storage.
        _upload_os.replace(str(temp_path), str(final_path))
        saved_path = final_path

        relative_path = kind + "/" + stored_name

        mime_type = (
            _upload_mimetypes.guess_type(original_name)[0]
            or "application/octet-stream"
        )

        conn = db()

        # Migrate old databases without deleting existing records.
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(media)"
            ).fetchall()
        }

        migrations = {
            "file_path": "TEXT",
            "original_filename": "TEXT",
            "mime_type": "TEXT",
            "file_size": "INTEGER"
        }

        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(
                    "ALTER TABLE media ADD COLUMN "
                    + column + " " + definition
                )

        cursor = conn.execute(
            """
            INSERT INTO media
            (
                title,
                type,
                category,
                description,
                status,
                year,
                file_path,
                original_filename,
                mime_type,
                file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                typ,
                category,
                description,
                "PENDING",
                _UploadDate.now().year,
                relative_path,
                original_name[:255],
                mime_type,
                file_size
            )
        )

        media_id = cursor.lastrowid
        conn.commit()

        return jsonify({
            "ok": True,
            "message": "Media uploaded successfully",
            "id": media_id,
            "title": title,
            "type": typ,
            "status": "PENDING",
            "filename": stored_name,
            "file_path": relative_path,
            "file_url": "/media-files/" + relative_path,
            "size": file_size
        }), 201

    except ValueError as error:

        if saved_path and saved_path.exists():
            saved_path.unlink()

        if temp_path.exists():
            temp_path.unlink()

        return jsonify({
            "ok": False,
            "error": str(error)
        }), 400

    except Exception:

        if conn is not None:
            conn.rollback()

        if saved_path and saved_path.exists():
            saved_path.unlink()

        if temp_path.exists():
            temp_path.unlink()

        app.logger.exception("MUVI GO media upload failed")

        return jsonify({
            "ok": False,
            "error": "upload_failed"
        }), 500

    finally:
        if conn is not None:
            conn.close()


# ===== END MUVI GO SECURE MEDIA UPLOAD V1 =====



if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
