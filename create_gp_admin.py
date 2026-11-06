import sqlite3
from pathlib import Path
from datetime import datetime
from getpass import getpass
from werkzeug.security import generate_password_hash
from app import app

email = "mrphiri56@gmail.com"

name = input("Administrator name: ").strip()
password = getpass("Create password (12+ characters): ")
confirm = getpass("Confirm password: ")

if not name or len(password) < 12 or password != confirm:
    raise SystemExit("Invalid name or passwords do not match / are too short.")

db_path = Path(app.config["DATABASE_PATH"])
if not db_path.is_file():
    raise SystemExit("Database not found. No changes made.")

backup_dir = Path("backups")
backup_dir.mkdir(exist_ok=True)
backup_path = backup_dir / (
    "before_gp_admin_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
)

db = sqlite3.connect(str(db_path))
try:
    with sqlite3.connect(str(backup_path)) as backup:
        db.backup(backup)

    columns = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    if not {"name", "email", "password_hash", "role"}.issubset(columns):
        raise SystemExit("Required user columns missing. No changes made.")

    if db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
        raise SystemExit("An admin already exists. No changes made.")

    if db.execute(
        "SELECT 1 FROM users WHERE lower(email)=lower(?)", (email,)
    ).fetchone():
        raise SystemExit("Email already exists. No changes made.")

    db.execute(
        "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)",
        (name, email, generate_password_hash(password), "admin")
    )
    db.commit()
    print("SUCCESS: Administrator account created.")
    print("Email:", email)
    print("Backup:", backup_path)
finally:
    db.close()
