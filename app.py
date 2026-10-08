import os
import sqlite3
from http.server import SimpleHTTPRequestHandler
from wsgiref.handlers import SimpleHandler

# ---------------------------------------------------------
# 1. إعداد قاعدة البيانات (SQLite)
# ---------------------------------------------------------
DB_NAME = "military_system.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # إنشاء الجداول الأساسية إن لم تكن موجودة
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            details TEXT
        )
    ''')
    conn.commit()
    conn.close()

# تشغيل التهيئة عند بدء الملف
init_db()

# ---------------------------------------------------------
# 2. فئة معالج الطلبات (HTTP Request Handler)
# ---------------------------------------------------------
class MilitarySystemHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # التوجيه الافتراضي للصفحة الرئيسية
        if self.path == '/' or self.path == '':
            self.path = '/index.html'
        
        # يمكنك إضافة المسارات (Routes) الخاصة بـ API أو الصفحات هنا
        if self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "system_online"}')
            return

        return super().do_GET()

    def do_POST(self):
        # استقبال و معالجة الطلبات القادمة للنظام
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"تم استلام البيانات بنجاح")

# ---------------------------------------------------------
# 3. واجهة WSGI الخاصة بنشر Vercel (بديل serve_forever)
# ---------------------------------------------------------
def app(environ, start_response):
    handler = SimpleHandler(
        environ['wsgi.input'],
        environ['wsgi.errors'],
        environ,
        multithread=False,
        multiprocess=False
    )
    handler.run(MilitarySystemHandler)
    return []

# ---------------------------------------------------------
# 4. التشغيل المحلي (ملاحظة: معطل لكي لا يعلق Vercel)
# ---------------------------------------------------------
# if __name__ == '__main__':
#     from http.server import ThreadingHTTPServer
#     server = ThreadingHTTPServer(('0.0.0.0', 8000), MilitarySystemHandler)
#     print("السيرفر يعمل محلياً...")
#     server.serve_forever()
