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
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)

from payments import payments_bp
from auth import auth as auth_bp, current_user

app.register_blueprint(payments_bp)
app.register_blueprint(auth_bp)

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
    return send_from_directory(
        BASE / "media" / "videos",
        "muvi-test.mp4",
        mimetype="video/mp4",
        conditional=True
    )





@app.route("/api/channels")
def channels_api():
    """Expose the existing frontend channel catalogue as read-only JSON."""
    import re
    from html import unescape

    js_path = BASE / "static" / "app.js"
    js = js_path.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+channels\s*=\s*\[(.*?)\n\];",
        js,
        re.S
    )
    if not match:
        return jsonify({"error": "Channel catalogue not found"}), 500

    pattern = re.compile(
        r'makeChannel\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,'
        r'\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)'
    )
    channels = []
    for name, category, channel_id, icon in pattern.findall(match.group(1)):
        channels.append({
            "name": name,
            "category": category,
            "id": channel_id,
            "icon": icon,
            "feed_status": "not_verified"
        })

    return jsonify(channels)


@app.route("/api/library")
def media_library_api():
    """List playable files found in the approved local media folders."""
    allowed = {
        "videos": {".mp4", ".webm", ".m4v", ".mov"},
        "music": {".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac", ".opus"},
    }
    items = []
    for kind, extensions in allowed.items():
        folder = BASE / "media" / kind
        folder.mkdir(parents=True, exist_ok=True)
        for item in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
            if not item.is_file() or item.is_symlink():
                continue
            if item.suffix.lower() not in extensions:
                continue
            items.append({
                "title": item.stem.replace("_", " ").replace("-", " "),
                "type": "video" if kind == "videos" else "music",
                "filename": item.name,
                "url": "/media-files/" + kind + "/" + quote(item.name),
            })
    return jsonify(items)


@app.route("/media-files/<kind>/<path:filename>")
def serve_media_file(kind, filename):
    """Serve only supported media files from the video/music folders."""
    allowed = {
        "videos": {".mp4", ".webm", ".m4v", ".mov"},
        "music": {".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac", ".opus"},
    }
    if kind not in allowed:
        return jsonify({"error": "unsupported media folder"}), 404

    folder = BASE / "media" / kind
    target = folder / filename
    if target.is_symlink() or target.suffix.lower() not in allowed[kind]:
        return jsonify({"error": "media file not found"}), 404

    return send_from_directory(
        str(folder), filename, conditional=True
    )

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
    return render_template("account.html", user=user)


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

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)



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
