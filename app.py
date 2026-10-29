"""HelpDesk AI: AI-assisted IT help desk and service ticket system (Flask + SQLite).

Run:  python app.py      then open http://127.0.0.1:5000
"""
import logging
import os
import re
import secrets
import sqlite3
from functools import wraps

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from triage import CATEGORIES, PRIORITIES, triage

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATUSES = ("Open", "In Progress", "Resolved", "Closed")


def _load_secret_key():
    """Use SECRET_KEY from the environment, otherwise create and reuse a local one."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(BASE_DIR, ".secret_key")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(key)
        except OSError:
            pass  # read-only disk: the key lasts for this process only
        return key


app = Flask(__name__)
app.config.update(
    DATABASE=os.environ.get("DATABASE", os.path.join(BASE_DIR, "helpdesk.db")),
    SECRET_KEY=_load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)
logging.basicConfig(level=logging.INFO)


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with open(os.path.join(BASE_DIR, "schema.sql"), "r", encoding="utf-8") as f:
        script = f.read()
    db = get_db()
    db.executescript(script)
    db.commit()


# --------------------------------------------------------------------------
# Security helpers: login guard, CSRF for forms and for the JSON API
# --------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="Please log in first."), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def csrf_ok():
    sent = request.form.get("_csrf", "")
    return bool(sent) and secrets.compare_digest(sent, session.get("_csrf", ""))


@app.before_request
def api_csrf_guard():
    """State-changing API calls must send the session's CSRF token in a header."""
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if "user_id" not in session:
            return None  # login_required answers with 401
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            return jsonify(error="Missing or invalid CSRF token. Refresh the page."), 403
    return None


def safe_next(target):
    """Only allow redirects to a path on this site (prevents open redirects)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("dashboard")


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")


def _text(data, key, label, errors, min_len, max_len):
    value = data.get(key)
    value = value.strip() if isinstance(value, str) else ""
    if len(value) < min_len:
        errors[key] = f"{label} is required." if min_len <= 1 else f"{label} must be at least {min_len} characters."
    elif len(value) > max_len:
        errors[key] = f"{label} must be {max_len} characters or fewer."
    return value


def validate_ticket(data):
    """Return (clean, errors). category/priority may be blank: triage fills them in."""
    errors = {}
    clean = {
        "title": _text(data, "title", "Title", errors, 5, 120),
        "description": _text(data, "description", "Description", errors, 10, 2000),
        "requester_name": _text(data, "requester_name", "Requester name", errors, 2, 80),
    }
    email = data.get("requester_email")
    email = email.strip() if isinstance(email, str) else ""
    if email and (len(email) > 120 or not EMAIL_RE.match(email)):
        errors["requester_email"] = "Enter a valid email address."
    clean["requester_email"] = email or None

    for key, allowed, label in (("category", CATEGORIES, "category"), ("priority", PRIORITIES, "priority")):
        value = data.get(key)
        value = value.strip() if isinstance(value, str) else ""
        if value and value not in allowed:
            errors[key] = f"Choose a valid {label}."
        clean[key] = value or None

    status = data.get("status")
    if status is not None and status != "":
        if status not in STATUSES:
            errors["status"] = "Choose a valid status."
        clean["status"] = status
    else:
        clean["status"] = None
    return clean, errors


def validate_comment(data):
    errors = {}
    body = _text(data, "body", "Comment", errors, 1, 1000)
    return {"body": body}, errors


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def bad_request(message="Invalid request.", fields=None):
    body = {"error": message}
    if fields:
        body["fields"] = fields
    return jsonify(body), 400


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------
def _like(term):
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


PRIORITY_ORDER_SQL = ("CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 "
                      "WHEN 'Medium' THEN 2 ELSE 3 END")
STATUS_ORDER_SQL = "CASE status WHEN 'Open' THEN 0 WHEN 'In Progress' THEN 1 WHEN 'Resolved' THEN 2 ELSE 3 END"


def list_tickets(db, q="", status="", category="", priority=""):
    sql = ("SELECT t.*, (SELECT COUNT(*) FROM comments c WHERE c.ticket_id = t.id) AS comment_count"
           " FROM tickets t WHERE 1=1")
    params = []
    if q:
        sql += (" AND (title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\'"
                " OR requester_name LIKE ? ESCAPE '\\' OR CAST(id AS TEXT) = ?)")
        params += [_like(q), _like(q), _like(q), q.lstrip("#")]
    if status in STATUSES:
        sql += " AND status = ?"
        params.append(status)
    if category in CATEGORIES:
        sql += " AND category = ?"
        params.append(category)
    if priority in PRIORITIES:
        sql += " AND priority = ?"
        params.append(priority)
    sql += f" ORDER BY {STATUS_ORDER_SQL}, {PRIORITY_ORDER_SQL}, created_at DESC, id DESC"
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def summary(db):
    out = {"total": 0, "Open": 0, "In Progress": 0, "Resolved": 0, "Closed": 0, "urgent_open": 0}
    for r in db.execute("SELECT status, COUNT(*) n FROM tickets GROUP BY status"):
        out[r["status"]] = r["n"]
        out["total"] += r["n"]
    out["urgent_open"] = db.execute(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('Open','In Progress')"
        " AND priority IN ('Critical','High')").fetchone()[0]
    return out


def get_ticket(db, ticket_id):
    row = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not csrf_ok():
            flash("Your session expired. Please try again.", "danger")
            return redirect(url_for("login"))
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            return redirect(safe_next(request.args.get("next")))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    values = {}
    if request.method == "POST":
        if not csrf_ok():
            flash("Your session expired. Please try again.", "danger")
            return redirect(url_for("register"))
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        values = {"full_name": full_name, "username": username}

        problems = []
        if not 2 <= len(full_name) <= 80:
            problems.append("Full name must be 2 to 80 characters.")
        if not USERNAME_RE.match(username):
            problems.append("Username: 3-30 characters, lowercase letters, numbers, dot or underscore.")
        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            problems.append("Password must be at least 8 characters and include a letter and a number.")
        if password != confirm:
            problems.append("Passwords do not match.")

        if not problems:
            try:
                db = get_db()
                db.execute("INSERT INTO users (username, full_name, password_hash) VALUES (?, ?, ?)",
                           (username, full_name, generate_password_hash(password)))
                db.commit()
                flash("Account created. You can log in now.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                problems.append("That username is already taken.")
        for p in problems:
            flash(p, "danger")
    return render_template("register.html", values=values)


@app.route("/logout", methods=["POST"])
def logout():
    if csrf_ok():
        session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", categories=CATEGORIES, priorities=PRIORITIES,
                           statuses=STATUSES)


@app.route("/tickets/<int:ticket_id>")
@login_required
def ticket_page(ticket_id):
    if get_ticket(get_db(), ticket_id) is None:
        return render_template("error.html", code=404, message="That ticket does not exist."), 404
    return render_template("ticket.html", ticket_id=ticket_id, categories=CATEGORIES,
                           priorities=PRIORITIES, statuses=STATUSES)


# --------------------------------------------------------------------------
# JSON API: tickets
# --------------------------------------------------------------------------
@app.route("/api/tickets", methods=["GET"])
@login_required
def api_tickets_list():
    db = get_db()
    tickets = list_tickets(
        db,
        q=request.args.get("q", "").strip()[:60],
        status=request.args.get("status", "").strip(),
        category=request.args.get("category", "").strip(),
        priority=request.args.get("priority", "").strip(),
    )
    return jsonify(tickets=tickets, summary=summary(db))


@app.route("/api/triage", methods=["POST"])
@login_required
def api_triage_preview():
    """Live preview used by the new-ticket form. Saves nothing."""
    data = json_body()
    if data is None:
        return bad_request("Send the ticket text as JSON.")
    title = data.get("title") if isinstance(data.get("title"), str) else ""
    description = data.get("description") if isinstance(data.get("description"), str) else ""
    return jsonify(triage(title[:120], description[:2000]))


@app.route("/api/tickets", methods=["POST"])
@login_required
def api_tickets_create():
    data = json_body()
    if data is None:
        return bad_request("Send the ticket details as JSON.")
    clean, errors = validate_ticket(data)
    if errors:
        return bad_request("Please fix the highlighted fields.", errors)

    suggestion = triage(clean["title"], clean["description"])
    category = clean["category"] or suggestion["category"]
    priority = clean["priority"] or suggestion["priority"]
    db = get_db()
    cur = db.execute(
        "INSERT INTO tickets (title, description, requester_name, requester_email,"
        " category, priority, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (clean["title"], clean["description"], clean["requester_name"], clean["requester_email"],
         category, priority, session["user_id"]))
    db.commit()
    return jsonify(id=cur.lastrowid, category=category, priority=priority), 201


@app.route("/api/tickets/<int:ticket_id>", methods=["GET"])
@login_required
def api_tickets_get(ticket_id):
    db = get_db()
    ticket = get_ticket(db, ticket_id)
    if ticket is None:
        return jsonify(error="Ticket not found."), 404
    comments = [dict(r) for r in db.execute(
        "SELECT * FROM comments WHERE ticket_id = ? ORDER BY id", (ticket_id,))]
    return jsonify(ticket=ticket, comments=comments,
                   triage=triage(ticket["title"], ticket["description"]))


@app.route("/api/tickets/<int:ticket_id>", methods=["PUT"])
@login_required
def api_tickets_update(ticket_id):
    data = json_body()
    if data is None:
        return bad_request("Send the ticket details as JSON.")
    clean, errors = validate_ticket(data)
    if errors:
        return bad_request("Please fix the highlighted fields.", errors)
    db = get_db()
    existing = get_ticket(db, ticket_id)
    if existing is None:
        return jsonify(error="Ticket not found."), 404
    # blank category/priority/status on update means "keep what is already set"
    clean["category"] = clean["category"] or existing["category"]
    clean["priority"] = clean["priority"] or existing["priority"]
    clean["status"] = clean["status"] or existing["status"]
    db.execute(
        "UPDATE tickets SET title=:title, description=:description, requester_name=:requester_name,"
        " requester_email=:requester_email, category=:category, priority=:priority, status=:status,"
        " updated_at=datetime('now') WHERE id=:id", {**clean, "id": ticket_id})
    db.commit()
    return jsonify(ok=True)


@app.route("/api/tickets/<int:ticket_id>/status", methods=["PUT"])
@login_required
def api_tickets_status(ticket_id):
    data = json_body()
    if data is None:
        return bad_request("Send the status as JSON.")
    status = data.get("status")
    if status not in STATUSES:
        return bad_request("Please fix the highlighted fields.", {"status": "Choose a valid status."})
    db = get_db()
    cur = db.execute("UPDATE tickets SET status = ?, updated_at = datetime('now') WHERE id = ?",
                     (status, ticket_id))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Ticket not found."), 404
    return jsonify(ok=True)


@app.route("/api/tickets/<int:ticket_id>", methods=["DELETE"])
@login_required
def api_tickets_delete(ticket_id):
    db = get_db()
    cur = db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Ticket not found."), 404
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# JSON API: comments
# --------------------------------------------------------------------------
@app.route("/api/tickets/<int:ticket_id>/comments", methods=["POST"])
@login_required
def api_comments_create(ticket_id):
    db = get_db()
    if get_ticket(db, ticket_id) is None:
        return jsonify(error="Ticket not found."), 404
    data = json_body()
    if data is None:
        return bad_request("Send the comment as JSON.")
    clean, errors = validate_comment(data)
    if errors:
        return bad_request("Please fix the highlighted fields.", errors)
    cur = db.execute("INSERT INTO comments (ticket_id, author_name, body) VALUES (?, ?, ?)",
                     (ticket_id, session.get("full_name", "Technician"), clean["body"]))
    db.execute("UPDATE tickets SET updated_at = datetime('now') WHERE id = ?", (ticket_id,))
    db.commit()
    return jsonify(id=cur.lastrowid), 201


@app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
@login_required
def api_comments_delete(comment_id):
    db = get_db()
    cur = db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Comment not found."), 404
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
def _error_response(code, message):
    if request.path.startswith("/api/"):
        return jsonify(error=message), code
    return render_template("error.html", code=code, message=message), code


@app.errorhandler(HTTPException)
def handle_http_error(err):
    messages = {404: "That page does not exist.", 405: "That action is not allowed here.",
                413: "The request was too large."}
    return _error_response(err.code, messages.get(err.code, err.description))


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    app.logger.exception("Unhandled error: %s", err)
    return _error_response(500, "Something went wrong on our side. Please try again.")


# Create the tables on startup (safe to repeat).
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
