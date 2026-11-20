"""Portfolio backend: a Flask app (Python) that serves the website and its API.

Features
- Serves index.html (the website) from Python.
- /api/status   : reports the Python version and server time.
- /api/counter  : the 4-bit binary counter logic, computed in Python.
- /api/contact  : validates contact-form messages and stores them in SQLite.
No passwords or API keys are needed.
"""
import html
import os
import platform
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from importlib.metadata import version

from flask import Flask, abort, jsonify, request, send_from_directory

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "data.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")  # optional: lets me open /messages
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IST = timezone(timedelta(hours=5, minutes=30))


def query(sql, args=(), commit=False):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, args).fetchall()
        if commit:
            con.commit()
        return rows
    finally:
        con.close()


query(
    "CREATE TABLE IF NOT EXISTS messages ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, "
    "message TEXT, created TEXT)",
    commit=True,
)

hits = {}  # ip -> timestamps, a simple rate limit


def too_many(ip, limit=5):
    now = time.time()
    recent = [t for t in hits.get(ip, []) if now - t < 3600]
    blocked = len(recent) >= limit
    if not blocked:
        recent.append(now)
    hits[ip] = recent
    return blocked


@app.get("/")
def home():
    return send_from_directory(app.root_path, "index.html")


@app.get("/api/status")
def status():
    return jsonify(
        python=platform.python_version(),
        flask=version("flask"),
        time=datetime.now(IST).strftime("%d %b %Y, %H:%M IST"),
    )


@app.get("/api/counter")
def counter():
    try:
        n = int(request.args.get("n", 0))
    except ValueError:
        return jsonify(error="n must be a whole number"), 400
    nxt = (n % 16 + 1) % 16  # 4-bit counter: 0000 to 1111, then wraps to 0000
    return jsonify(next=nxt, binary=format(nxt, "04b"))


@app.post("/api/contact")
def contact():
    data = request.get_json(silent=True) or {}
    if data.get("website"):  # hidden trap field that only bots fill in
        return jsonify(ok=True)
    name = " ".join(str(data.get("name", "")).split())
    email = str(data.get("email", "")).strip()
    message = str(data.get("message", "")).strip()
    if not 1 <= len(name) <= 80:
        return jsonify(error="Please enter your name."), 400
    if not EMAIL_RE.match(email) or len(email) > 120:
        return jsonify(error="Please enter a valid email address."), 400
    if not 10 <= len(message) <= 2000:
        return jsonify(error="Message must be 10 to 2000 characters."), 400
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if too_many(ip):
        return jsonify(error="Too many messages. Please try again later."), 429
    created = datetime.now(IST).isoformat(timespec="seconds")
    query("INSERT INTO messages (name, email, message, created) VALUES (?, ?, ?, ?)",
          (name, email, message, created), commit=True)
    app.logger.info("NEW MESSAGE from %s <%s>: %s", name, email, message)
    return jsonify(ok=True)


@app.get("/messages")
def messages():
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(404)
    rows = query("SELECT * FROM messages ORDER BY id DESC")
    items = "".join(
        f"<p><b>{html.escape(r['name'])}</b> &lt;{html.escape(r['email'])}&gt; "
        f"<i>{r['created']}</i><br>{html.escape(r['message'])}</p><hr>"
        for r in rows
    )
    return f"<h1>Messages</h1>{items or '<p>No messages yet.</p>'}"


if __name__ == "__main__":
    app.run(debug=True)
