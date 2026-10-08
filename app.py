#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام إدارة الوحدة العسكرية والتشكيلات الشامل (Comprehensive Military ERP)
دعم كامل للكتائب، السرايا، الفصائل، التموين، الموارد البشرية، والمالية.
يدعم PostgreSQL السحابية و SQLite المحلية تلقائياً.
"""
import os, sys, json, time, secrets, hashlib, traceback, sqlite3
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# إعدادات البيئة
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
SESSION_HOURS = 8

# محاولة تحميل مكتبة psycopg2 لقواعد بيانات PostgreSQL السحابية
HAS_PG = False
if DATABASE_URL:
    try:
        import psycopg2
        import psycopg2.extras
        HAS_PG = True
    except ImportError:
        HAS_PG = False

# ------------------------------------------------------------------ الاتصال بقاعدة البيانات
def get_db():
    if HAS_PG and DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn, "pg"
    else:
        db_path = os.environ.get("MIL_DB", os.path.join(BASE_DIR, "military.db"))
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn, "lite"

# ------------------------------------------------------------------ المخطط الشامل (Schema)
SCHEMA_LITE = """
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL, -- قيادة, لواء, فوج, كتيبة, سرية, فصيلة, جماعة
    parent_id INTEGER REFERENCES units(id)
);

CREATE TABLE IF NOT EXISTS ranks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL -- ضباط كبار, ضباط, ضباط صف, أفراد
);

CREATE TABLE IF NOT EXISTS personnel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    military_no TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    rank_id INTEGER REFERENCES ranks(id),
    position TEXT,
    unit_id INTEGER REFERENCES units(id),
    hire_date TEXT,
    salary REAL DEFAULT 0,
    phone TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    unit_id INTEGER REFERENCES units(id),
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    failed INTEGER DEFAULT 0,
    locked_until TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fin_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    ref TEXT,
    description TEXT,
    created_by TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL REFERENCES journal(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES fin_accounts(id),
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    memo TEXT
);

CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit_id INTEGER REFERENCES units(id),
    location TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT, -- تموين, ذخيرة, أسلحة, قطع غيار
    measure TEXT,
    min_qty REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    move_date TEXT NOT NULL,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    move_type TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_cost REAL DEFAULT 0,
    ref TEXT,
    notes TEXT,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    details TEXT,
    ip TEXT
);
"""

# ------------------------------------------------------------------ التحديث والتهيئة
def init_db():
    conn, mode = get_db()
    if mode == "lite":
        conn.executescript(SCHEMA_LITE)
        # إدخال البيانات الأولية
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            salt = secrets.token_hex(16)
            pw_hash = hashlib.pbkdf2_hmac("sha256", "Admin@12345".encode(), bytes.fromhex(salt), 600000).hex()
            conn.execute("INSERT INTO users (username, full_name, role, pw_hash, salt) VALUES (?, ?, ?, ?, ?)",
                         ("admin", "مدير النظام العسكري", "admin", pw_hash, salt))
            
            # إضافة الرتب الأساسية
            for code, title, cat in [("R1", "جندي", "أفراد"), ("R2", "عريف", "ضباط صف"), ("R3", "رقيب", "ضباط صف"),
                                      ("R4", "ملازم", "ضباط"), ("R5", "نقيب", "ضباط"), ("R6", "مقدم", "ضباط كبار"), ("R7", "عقيد", "ضباط كبار")]:
                conn.execute("INSERT INTO ranks (code, title, category) VALUES (?, ?, ?)", (code, title, cat))
        conn.commit()
    conn.close()

# ------------------------------------------------------------------ واجهة الدخول المدمجة
HTML_INTERFACE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>نظام إدارة القيادة والوحدات العسكرية المتكامل</title>
    <style>
        :root { --bg: #0b1329; --card: #1c2541; --primary: #3a506b; --accent: #457b9d; --text: #edf2f4; }
        body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .login-box { background: var(--card); padding: 2.5rem; border-radius: 12px; border: 1px solid #5bc0be; width: 100%; max-width: 420px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); text-align: center; }
        h1 { font-size: 1.4rem; color: #5bc0be; margin-bottom: 1.5rem; }
        .form-group { text-align: right; margin-bottom: 1rem; }
        label { display: block; font-size: 0.85rem; margin-bottom: 0.3rem; color: #a5a5a5; }
        input { width: 100%; padding: 0.8rem; border-radius: 6px; border: 1px solid #3a506b; background: #0b1329; color: white; box-sizing: border-box; }
        button { width: 100%; padding: 0.8rem; border: none; border-radius: 6px; background: #5bc0be; color: #0b1329; font-weight: bold; cursor: pointer; margin-top: 1rem; font-size: 1rem; }
        button:hover { background: #3a506b; color: white; }
        .info { margin-top: 1.5rem; font-size: 0.8rem; color: #8d99ae; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>نظام إدارة القيادة والتشكيلات العسكرية</h1>
        <form id="lform">
            <div class="form-group">
                <label>اسم المستخدم</label>
                <input type="text" id="un" value="admin" required>
            </div>
            <div class="form-group">
                <label>كلمة المرور</label>
                <input type="password" id="pw" value="Admin@12345" required>
            </div>
            <button type="submit">تسجيل الدخول</button>
        </form>
        <div class="info">
            النظام يدعم: القيادات، اللواءات، الكتايب، السرايا، الفصائل، الموارد البشرية، والمالية.
        </div>
    </div>
</body>
</html>"""

# ------------------------------------------------------------------ معالج الطلبات السحابي
class MilitaryServerHandler(BaseHTTPRequestHandler):
    def send_res(self, code, data, ctype="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self.send_res(200, HTML_INTERFACE.encode('utf-8'), "text/html")
        else:
            self.send_res(404, {"error": "المسار غير موجود"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/login":
            length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(length) or "{}")
            if payload.get("username") == "admin" and payload.get("password") == "Admin@12345":
                self.send_res(200, {"status": "success", "token": secrets.token_hex(16), "role": "admin"})
            else:
                self.send_res(401, {"error": "بيانات الدخول غير صحيحة"})
        else:
            self.send_res(404, {"error": "غير موجود"})

if __name__ == "__main__":
    init_db()
    print(f"النظام العسكري الشامل يعمل بنجاح على المخرج: {PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MilitaryServerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nتم إيقاف النظام.")



تقصد هذا الكود الذي تضعه في المربع الكبير#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام إدارة الوحدة العسكرية والتشكيلات الشامل (Comprehensive Military ERP)
دعم كامل للكتائب، السرايا، الفصائل، التموين، الموارد البشرية، والمالية.
يدعم PostgreSQL السحابية و SQLite المحلية تلقائياً.
"""
import os, sys, json, time, secrets, hashlib, traceback, sqlite3
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# إعدادات البيئة
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
SESSION_HOURS = 8

# محاولة تحميل مكتبة psycopg2 لقواعد بيانات PostgreSQL السحابية
HAS_PG = False
if DATABASE_URL:
    try:
        import psycopg2
        import psycopg2.extras
        HAS_PG = True
    except ImportError:
        HAS_PG = False

# ------------------------------------------------------------------ الاتصال بقاعدة البيانات
def get_db():
    if HAS_PG and DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn, "pg"
    else:
        db_path = os.environ.get("MIL_DB", os.path.join(BASE_DIR, "military.db"))
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn, "lite"

# ------------------------------------------------------------------ المخطط الشامل (Schema)
SCHEMA_LITE = """
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL, -- قيادة, لواء, فوج, كتيبة, سرية, فصيلة, جماعة
    parent_id INTEGER REFERENCES units(id)
);

CREATE TABLE IF NOT EXISTS ranks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL -- ضباط كبار, ضباط, ضباط صف, أفراد
);

CREATE TABLE IF NOT EXISTS personnel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    military_no TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    rank_id INTEGER REFERENCES ranks(id),
    position TEXT,
    unit_id INTEGER REFERENCES units(id),
    hire_date TEXT,
    salary REAL DEFAULT 0,
    phone TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    unit_id INTEGER REFERENCES units(id),
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    failed INTEGER DEFAULT 0,
    locked_until TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fin_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    ref TEXT,
    description TEXT,
    created_by TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_id INTEGER NOT NULL REFERENCES journal(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES fin_accounts(id),
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    memo TEXT
);

CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit_id INTEGER REFERENCES units(id),
    location TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT, -- تموين, ذخيرة, أسلحة, قطع غيار
    measure TEXT,
    min_qty REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    move_date TEXT NOT NULL,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    move_type TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_cost REAL DEFAULT 0,
    ref TEXT,
    notes TEXT,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    details TEXT,
    ip TEXT
);
"""

# ------------------------------------------------------------------ التحديث والتهيئة
def init_db():
    conn, mode = get_db()
    if mode == "lite":
        conn.executescript(SCHEMA_LITE)
        # إدخال البيانات الأولية
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            salt = secrets.token_hex(16)
            pw_hash = hashlib.pbkdf2_hmac("sha256", "Admin@12345".encode(), bytes.fromhex(salt), 600000).hex()
            conn.execute("INSERT INTO users (username, full_name, role, pw_hash, salt) VALUES (?, ?, ?, ?, ?)",
                         ("admin", "مدير النظام العسكري", "admin", pw_hash, salt))
            
            # إضافة الرتب الأساسية
            for code, title, cat in [("R1", "جندي", "أفراد"), ("R2", "عريف", "ضباط صف"), ("R3", "رقيب", "ضباط صف"),
                                      ("R4", "ملازم", "ضباط"), ("R5", "نقيب", "ضباط"), ("R6", "مقدم", "ضباط كبار"), ("R7", "عقيد", "ضباط كبار")]:
                conn.execute("INSERT INTO ranks (code, title, category) VALUES (?, ?, ?)", (code, title, cat))
        conn.commit()
    conn.close()

# ------------------------------------------------------------------ واجهة الدخول المدمجة
HTML_INTERFACE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>نظام إدارة القيادة والوحدات العسكرية المتكامل</title>
    <style>
        :root { --bg: #0b1329; --card: #1c2541; --primary: #3a506b; --accent: #457b9d; --text: #edf2f4; }
        body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .login-box { background: var(--card); padding: 2.5rem; border-radius: 12px; border: 1px solid #5bc0be; width: 100%; max-width: 420px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); text-align: center; }
        h1 { font-size: 1.4rem; color: #5bc0be; margin-bottom: 1.5rem; }
        .form-group { text-align: right; margin-bottom: 1rem; }
        label { display: block; font-size: 0.85rem; margin-bottom: 0.3rem; color: #a5a5a5; }
        input { width: 100%; padding: 0.8rem; border-radius: 6px; border: 1px solid #3a506b; background: #0b1329; color: white; box-sizing: border-box; }
        button { width: 100%; padding: 0.8rem; border: none; border-radius: 6px; background: #5bc0be; color: #0b1329; font-weight: bold; cursor: pointer; margin-top: 1rem; font-size: 1rem; }
        button:hover { background: #3a506b; color: white; }
        .info { margin-top: 1.5rem; font-size: 0.8rem; color: #8d99ae; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>نظام إدارة القيادة والتشكيلات العسكرية</h1>
        <form id="lform">
            <div class="form-group">
                <label>اسم المستخدم</label>
                <input type="text" id="un" value="admin" required>
            </div>
            <div class="form-group">
                <label>كلمة المرور</label>
                <input type="password" id="pw" value="Admin@12345" required>
            </div>
            <button type="submit">تسجيل الدخول</button>
        </form>
        <div class="info">
            النظام يدعم: القيادات، اللواءات، الكتايب، السرايا، الفصائل، الموارد البشرية، والمالية.
        </div>
    </div>
</body>
</html>"""

# ------------------------------------------------------------------ معالج الطلبات السحابي
class MilitaryServerHandler(BaseHTTPRequestHandler):
    def send_res(self, code, data, ctype="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self.send_res(200, HTML_INTERFACE.encode('utf-8'), "text/html")
        else:
            self.send_res(404, {"error": "المسار غير موجود"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/login":
            length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(length) or "{}")
            if payload.get("username") == "admin" and payload.get("password") == "Admin@12345":
                self.send_res(200, {"status": "success", "token": secrets.token_hex(16), "role": "admin"})
            else:
                self.send_res(401, {"error": "بيانات الدخول غير صحيحة"})
        else:
            self.send_res(404, {"error": "غير موجود"})

if __name__ == "__main__":
    init_db()
    print(f"النظام العسكري الشامل يعمل بنجاح على المخرج: {PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MilitaryServerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nتم إيقاف النظام.")
from http.server import SimpleHTTPRequestHandler
# ... بقية استيراداتك ودوالك كما هي ...

# أضف هذا المعالج في أسفل الملف مباشرة
def handler(request, response):
    # تحويل طلبات Vercel إلى Handler الخاص بك
    return app(request, response)
import os
from http.server import SimpleHTTPRequestHandler

# أضف هذا الجزء في نهاية الملف تماماً بدلاً من handler القديمة:
class VercelHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        super().do_GET()

app = VercelHandler
