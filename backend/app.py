import argparse
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from getpass import getpass
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "yallago.db"
SECRET_KEY = os.environ.get("YALLAGO_SECRET_KEY")

if not SECRET_KEY:
    # Development convenience only. Set YALLAGO_SECRET_KEY to a long random
    # secret in the environment before using real school data.
    SECRET_KEY = secrets.token_urlsafe(48)
    print("WARNING: using a temporary development signing key.")
    print("Set YALLAGO_SECRET_KEY in the environment for persistent sessions.")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="yallago-auth-v1")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','supervisor','reception')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_number TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    class_id INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_code TEXT NOT NULL UNIQUE,
    employee_id INTEGER NOT NULL UNIQUE,
    class_id INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    FOREIGN KEY(employee_id) REFERENCES employees(id),
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE IF NOT EXISTS attendance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('arrival','departure','handover')),
    recorded_by INTEGER NOT NULL,
    device_id INTEGER,
    recorded_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id),
    FOREIGN KEY(recorded_by) REFERENCES employees(id),
    FOREIGN KEY(device_id) REFERENCES devices(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_employee_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(actor_employee_id) REFERENCES employees(id)
);
"""

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)

def audit(actor_id, action, entity_type, entity_id=None, details=""):
    db = get_db()
    db.execute(
        """INSERT INTO audit_log
           (actor_employee_id, action, entity_type, entity_id, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (actor_id, action, entity_type, entity_id, details, now_iso()),
    )
    db.commit()

def make_token(employee, device_id=None, class_id=None):
    return serializer.dumps({
        "employee_id": employee["id"],
        "role": employee["role"],
        "device_id": device_id,
        "class_id": class_id,
    })

def current_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    try:
        return serializer.loads(token, max_age=60 * 60 * 12)
    except (BadSignature, SignatureExpired):
        return None

def authenticated(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        identity = current_user()
        if not identity:
            return jsonify({"error": "Authentication required or token expired."}), 401
        db = get_db()
        employee = db.execute(
            "SELECT id, username, display_name, role, is_active FROM employees WHERE id=?",
            (identity["employee_id"],),
        ).fetchone()
        if not employee or not employee["is_active"]:
            return jsonify({"error": "Account is inactive."}), 403
        g.identity = identity
        g.employee = employee
        return fn(*args, **kwargs)
    return wrapper

def admin_only(fn):
    @wraps(fn)
    @authenticated
    def wrapper(*args, **kwargs):
        if g.employee["role"] != "admin":
            return jsonify({"error": "Administrator permission required."}), 403
        return fn(*args, **kwargs)
    return wrapper

def json_error(message, status=400):
    return jsonify({"error": message}), status

def require_fields(data, fields):
    missing = [field for field in fields if not data.get(field)]
    if missing:
        return "Missing required field(s): " + ", ".join(missing)
    return None

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "application": "YallaGo API", "version": "0.2"})

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    error = require_fields(data, ["username", "password"])
    if error:
        return json_error(error)

    db = get_db()
    employee = db.execute(
        "SELECT * FROM employees WHERE username=?",
        (str(data["username"]).strip(),),
    ).fetchone()

    if not employee or not employee["is_active"]:
        return json_error("Invalid username or password.", 401)
    if not check_password_hash(employee["password_hash"], str(data["password"])):
        return json_error("Invalid username or password.", 401)

    device_id = None
    class_id = None
    device_code = data.get("device_code")

    if employee["role"] == "supervisor":
        if not device_code:
            return json_error("This supervisor account requires its registered device.", 403)
        device = db.execute(
            """SELECT d.id, d.class_id, d.is_active
               FROM devices d
               WHERE d.device_code=? AND d.employee_id=?""",
            (str(device_code).strip(), employee["id"]),
        ).fetchone()
        if not device or not device["is_active"]:
            return json_error("This device is not authorized for this supervisor.", 403)
        class_row = db.execute(
            "SELECT is_active FROM classes WHERE id=?",
            (device["class_id"],),
        ).fetchone()
        if not class_row or not class_row["is_active"]:
            return json_error("The assigned class is inactive.", 403)
        device_id = device["id"]
        class_id = device["class_id"]
        db.execute(
            "UPDATE devices SET last_seen_at=? WHERE id=?",
            (now_iso(), device_id),
        )
        db.commit()

    token = make_token(employee, device_id, class_id)
    class_name = None
    if class_id:
        row = db.execute("SELECT name FROM classes WHERE id=?", (class_id,)).fetchone()
        class_name = row["name"] if row else None

    return jsonify({
        "token": token,
        "user": {
            "id": employee["id"],
            "username": employee["username"],
            "display_name": employee["display_name"],
            "role": employee["role"],
            "class_id": class_id,
            "class_name": class_name,
            "device_id": device_id,
        }
    })

@app.get("/api/me")
@authenticated
def me():
    identity = g.identity
    class_name = None
    if identity.get("class_id"):
        row = get_db().execute(
            "SELECT name FROM classes WHERE id=?",
            (identity["class_id"],),
        ).fetchone()
        class_name = row["name"] if row else None
    return jsonify({
        "id": g.employee["id"],
        "username": g.employee["username"],
        "display_name": g.employee["display_name"],
        "role": g.employee["role"],
        "class_id": identity.get("class_id"),
        "class_name": class_name,
    })

@app.get("/api/admin/classes")
@admin_only
def list_classes():
    rows = get_db().execute("SELECT * FROM classes ORDER BY name").fetchall()
    return jsonify([dict(row) for row in rows])

@app.post("/api/admin/classes")
@admin_only
def create_class():
    data = request.get_json(silent=True) or {}
    error = require_fields(data, ["name"])
    if error:
        return json_error(error)
    try:
        cur = get_db().execute(
            "INSERT INTO classes(name, created_at) VALUES (?, ?)",
            (str(data["name"]).strip(), now_iso()),
        )
        get_db().commit()
        audit(g.employee["id"], "create", "class", cur.lastrowid, data["name"])
        return jsonify({"id": cur.lastrowid, "name": data["name"]}), 201
    except sqlite3.IntegrityError:
        return json_error("A class with this name already exists.", 409)

@app.get("/api/admin/employees")
@admin_only
def list_employees():
    rows = get_db().execute(
        """SELECT id, username, display_name, role, is_active, created_at
           FROM employees ORDER BY display_name"""
    ).fetchall()
    return jsonify([dict(row) for row in rows])

@app.post("/api/admin/employees")
@admin_only
def create_employee():
    data = request.get_json(silent=True) or {}
    error = require_fields(data, ["username", "password", "display_name", "role"])
    if error:
        return json_error(error)
    role = str(data["role"])
    if role not in ("supervisor", "reception", "admin"):
        return json_error("Invalid role.")
    if len(str(data["password"])) < 10:
        return json_error("Use a password with at least 10 characters.")
    try:
        cur = get_db().execute(
            """INSERT INTO employees
               (username, password_hash, display_name, role, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                str(data["username"]).strip(),
                generate_password_hash(str(data["password"])),
                str(data["display_name"]).strip(),
                role,
                now_iso(),
            ),
        )
        get_db().commit()
        audit(g.employee["id"], "create", "employee", cur.lastrowid, role)
        return jsonify({"id": cur.lastrowid, "username": data["username"], "role": role}), 201
    except sqlite3.IntegrityError:
        return json_error("That username is already in use.", 409)

@app.get("/api/admin/students")
@admin_only
def list_students():
    rows = get_db().execute(
        """SELECT s.*, c.name AS class_name
           FROM students s JOIN classes c ON c.id=s.class_id
           ORDER BY c.name, s.full_name"""
    ).fetchall()
    return jsonify([dict(row) for row in rows])

@app.post("/api/admin/students")
@admin_only
def create_student():
    data = request.get_json(silent=True) or {}
    error = require_fields(data, ["student_number", "full_name", "class_id"])
    if error:
        return json_error(error)
    try:
        class_id = int(data["class_id"])
    except (TypeError, ValueError):
        return json_error("class_id must be a number.")
    class_row = get_db().execute(
        "SELECT id FROM classes WHERE id=? AND is_active=1", (class_id,)
    ).fetchone()
    if not class_row:
        return json_error("The selected class does not exist or is inactive.")
    try:
        cur = get_db().execute(
            """INSERT INTO students
               (student_number, full_name, class_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                str(data["student_number"]).strip(),
                str(data["full_name"]).strip(),
                class_id,
                now_iso(),
            ),
        )
        get_db().commit()
        audit(g.employee["id"], "create", "student", cur.lastrowid, str(data["student_number"]))
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return json_error("That student number is already registered.", 409)

@app.get("/api/admin/devices")
@admin_only
def list_devices():
    rows = get_db().execute(
        """SELECT d.id, d.device_code, d.employee_id, d.class_id,
                  d.is_active, d.created_at, d.last_seen_at,
                  e.display_name AS supervisor_name, c.name AS device_label
           FROM devices d
           JOIN employees e ON e.id=d.employee_id
           JOIN classes c ON c.id=d.class_id
           ORDER BY c.name, d.id"""
    ).fetchall()
    return jsonify([dict(row) for row in rows])

@app.post("/api/admin/devices")
@admin_only
def register_device():
    data = request.get_json(silent=True) or {}
    error = require_fields(data, ["device_code", "employee_id", "class_id"])
    if error:
        return json_error(error)
    try:
        employee_id = int(data["employee_id"])
        class_id = int(data["class_id"])
    except (TypeError, ValueError):
        return json_error("employee_id and class_id must be numbers.")

    db = get_db()
    employee = db.execute(
        "SELECT id, role, is_active FROM employees WHERE id=?", (employee_id,)
    ).fetchone()
    class_row = db.execute(
        "SELECT id, is_active FROM classes WHERE id=?", (class_id,)
    ).fetchone()
    if not employee or employee["role"] != "supervisor" or not employee["is_active"]:
        return json_error("Choose an active supervisor account.")
    if not class_row or not class_row["is_active"]:
        return json_error("Choose an active class.")

    try:
        cur = db.execute(
            """INSERT INTO devices(device_code, employee_id, class_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (str(data["device_code"]).strip(), employee_id, class_id, now_iso()),
        )
        db.commit()
        audit(g.employee["id"], "register", "device", cur.lastrowid, f"class_id={class_id}")
        return jsonify({
            "id": cur.lastrowid,
            "device_code": data["device_code"],
            "device_label": db.execute("SELECT name FROM classes WHERE id=?", (class_id,)).fetchone()["name"],
        }), 201
    except sqlite3.IntegrityError:
        return json_error(
            "This device code is already registered, or this supervisor already has a device.",
            409,
        )

@app.get("/api/admin/audit")
@admin_only
def audit_entries():
    rows = get_db().execute(
        """SELECT a.*, e.username AS actor_username
           FROM audit_log a LEFT JOIN employees e ON e.id=a.actor_employee_id
           ORDER BY a.id DESC LIMIT 200"""
    ).fetchall()
    return jsonify([dict(row) for row in rows])

@app.get("/api/supervisor/students")
@authenticated
def supervisor_students():
    if g.employee["role"] != "supervisor":
        return json_error("Supervisor permission required.", 403)
    class_id = g.identity.get("class_id")
    rows = get_db().execute(
        """SELECT id, student_number, full_name, class_id
           FROM students WHERE class_id=? AND is_active=1
           ORDER BY full_name""",
        (class_id,),
    ).fetchall()
    return jsonify([dict(row) for row in rows])

def create_admin():
    init_db()
    username = input("Administrator username: ").strip()
    while not username:
        username = input("Username cannot be empty. Enter username: ").strip()
    password = getpass("Administrator password (minimum 12 characters): ")
    while len(password) < 12:
        print("Please use at least 12 characters.")
        password = getpass("Administrator password: ")
    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match. No administrator was created.")
        return
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """INSERT INTO employees
               (username, password_hash, display_name, role, created_at)
               VALUES (?, ?, ?, 'admin', ?)""",
            (username, generate_password_hash(password), "School Administrator", now_iso()),
        )
        db.commit()
    print("Administrator created. Keep the credentials private.")


@app.patch("/api/admin/classes/<int:class_id>")
@admin_only
def update_class(class_id):
    data = request.get_json(silent=True) or {}
    allowed = {k: data[k] for k in ("name", "is_active") if k in data}
    if not allowed:
        return json_error("Provide name and/or is_active.")
    if "name" in allowed:
        allowed["name"] = str(allowed["name"]).strip()
        if not allowed["name"]:
            return json_error("Class name cannot be empty.")
    if "is_active" in allowed:
        allowed["is_active"] = 1 if bool(allowed["is_active"]) else 0
    assignments = ", ".join(f"{key}=?" for key in allowed)
    values = list(allowed.values()) + [class_id]
    try:
        cur = get_db().execute(f"UPDATE classes SET {assignments} WHERE id=?", values)
        get_db().commit()
        if cur.rowcount == 0:
            return json_error("Class not found.", 404)
        audit(g.employee["id"], "update", "class", class_id, str(allowed))
        return jsonify({"updated": True, "id": class_id})
    except sqlite3.IntegrityError:
        return json_error("A class with this name already exists.", 409)

@app.patch("/api/admin/employees/<int:employee_id>")
@admin_only
def update_employee(employee_id):
    data = request.get_json(silent=True) or {}
    allowed = {}
    if "display_name" in data:
        allowed["display_name"] = str(data["display_name"]).strip()
        if not allowed["display_name"]:
            return json_error("display_name cannot be empty.")
    if "role" in data:
        if data["role"] not in ("admin", "supervisor", "reception"):
            return json_error("Invalid role.")
        allowed["role"] = data["role"]
    if "is_active" in data:
        allowed["is_active"] = 1 if bool(data["is_active"]) else 0
    if "password" in data:
        if len(str(data["password"])) < 10:
            return json_error("Use a password with at least 10 characters.")
        allowed["password_hash"] = generate_password_hash(str(data["password"]))
    if not allowed:
        return json_error("No supported changes supplied.")
    assignments = ", ".join(f"{key}=?" for key in allowed)
    try:
        cur = get_db().execute(
            f"UPDATE employees SET {assignments} WHERE id=?",
            list(allowed.values()) + [employee_id],
        )
        get_db().commit()
        if cur.rowcount == 0:
            return json_error("Employee not found.", 404)
        audit(g.employee["id"], "update", "employee", employee_id, str(list(allowed.keys())))
        return jsonify({"updated": True, "id": employee_id})
    except sqlite3.IntegrityError:
        return json_error("The requested change conflicts with existing records.", 409)

@app.patch("/api/admin/students/<int:student_id>")
@admin_only
def update_student(student_id):
    data = request.get_json(silent=True) or {}
    allowed = {}
    if "student_number" in data:
        allowed["student_number"] = str(data["student_number"]).strip()
    if "full_name" in data:
        allowed["full_name"] = str(data["full_name"]).strip()
    if "class_id" in data:
        try:
            class_id = int(data["class_id"])
        except (TypeError, ValueError):
            return json_error("class_id must be a number.")
        active_class = get_db().execute(
            "SELECT id FROM classes WHERE id=? AND is_active=1", (class_id,)
        ).fetchone()
        if not active_class:
            return json_error("The selected class does not exist or is inactive.")
        allowed["class_id"] = class_id
    if "is_active" in data:
        allowed["is_active"] = 1 if bool(data["is_active"]) else 0
    if not allowed:
        return json_error("No supported changes supplied.")
    assignments = ", ".join(f"{key}=?" for key in allowed)
    try:
        cur = get_db().execute(
            f"UPDATE students SET {assignments} WHERE id=?",
            list(allowed.values()) + [student_id],
        )
        get_db().commit()
        if cur.rowcount == 0:
            return json_error("Student not found.", 404)
        audit(g.employee["id"], "update", "student", student_id, str(allowed))
        return jsonify({"updated": True, "id": student_id})
    except sqlite3.IntegrityError:
        return json_error("That student number is already registered.", 409)

@app.patch("/api/admin/devices/<int:device_id>")
@admin_only
def update_device(device_id):
    data = request.get_json(silent=True) or {}
    allowed = {}
    if "device_code" in data:
        allowed["device_code"] = str(data["device_code"]).strip()
        if not allowed["device_code"]:
            return json_error("device_code cannot be empty.")
    if "employee_id" in data:
        try:
            employee_id = int(data["employee_id"])
        except (TypeError, ValueError):
            return json_error("employee_id must be a number.")
        supervisor = get_db().execute(
            "SELECT id FROM employees WHERE id=? AND role='supervisor' AND is_active=1",
            (employee_id,),
        ).fetchone()
        if not supervisor:
            return json_error("Choose an active supervisor.")
        allowed["employee_id"] = employee_id
    if "class_id" in data:
        try:
            class_id = int(data["class_id"])
        except (TypeError, ValueError):
            return json_error("class_id must be a number.")
        active_class = get_db().execute(
            "SELECT id FROM classes WHERE id=? AND is_active=1", (class_id,)
        ).fetchone()
        if not active_class:
            return json_error("Choose an active class.")
        allowed["class_id"] = class_id
    if "is_active" in data:
        allowed["is_active"] = 1 if bool(data["is_active"]) else 0
    if not allowed:
        return json_error("No supported changes supplied.")
    assignments = ", ".join(f"{key}=?" for key in allowed)
    try:
        cur = get_db().execute(
            f"UPDATE devices SET {assignments} WHERE id=?",
            list(allowed.values()) + [device_id],
        )
        get_db().commit()
        if cur.rowcount == 0:
            return json_error("Device not found.", 404)
        audit(g.employee["id"], "update", "device", device_id, str(allowed))
        return jsonify({"updated": True, "id": device_id})
    except sqlite3.IntegrityError:
        return json_error(
            "Device code already exists, or this supervisor already has a registered device.",
            409,
        )


@app.get("/")
def dashboard():
    return send_from_directory(app.static_folder, "dashboard.html")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-admin", action="store_true")
    args = parser.parse_args()
    if args.create_admin:
        create_admin()
    else:
        init_db()
        app.run(host="0.0.0.0", port=5000, debug=False)


