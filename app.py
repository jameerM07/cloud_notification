
"""
Cloud-Based Notification System
Flask application with login, registration,
Redis notification queue and SQLite persistence.
"""

import os
import re
import uuid
import sqlite3

from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional, Tuple

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session,
    redirect,
    url_for,
    flash
)

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

import database
import queue_service


# --------------------------------------------------
# INITIALIZATION
# --------------------------------------------------

load_dotenv()

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "college-cloud-notification-demo-key-2026"
)

app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Initialize existing notification database
database.init_db()


# --------------------------------------------------
# USER DATABASE
# --------------------------------------------------

def init_users_table():
    """Create users table in the existing SQLite database."""

    with sqlite3.connect(database.get_db_path()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        conn.commit()


init_users_table()


# --------------------------------------------------
# LOGIN PROTECTION
# --------------------------------------------------

def login_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if "user_id" not in session:

            api_paths = (
                "/send-notification",
                "/notifications",
                "/retry-notification",
                "/queue-status",
                "/api/"
            )

            if request.path.startswith(api_paths):
                return jsonify({
                    "success": False,
                    "error": "Please login first."
                }), 401

            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return decorated_function


# --------------------------------------------------
# LOGIN PAGE
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not EMAIL_REGEX.match(email) or not email.endswith("@gmail.com"):
            flash("Please enter a valid Gmail address.")
            return render_template("login.html")

        with sqlite3.connect(database.get_db_path()) as conn:

            conn.row_factory = sqlite3.Row

            user = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

        if user and check_password_hash(user["password"], password):

            session.clear()
            session["user_id"] = user["id"]
            session["email"] = user["email"]

            return redirect(url_for("index"))

        flash("Invalid Gmail address or password.")

    return render_template("login.html")


# --------------------------------------------------
# REGISTRATION PAGE
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not EMAIL_REGEX.match(email) or not email.endswith("@gmail.com"):
            flash("Please enter a valid Gmail address.")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)

        try:

            with sqlite3.connect(database.get_db_path()) as conn:

                conn.execute(
                    """
                    INSERT INTO users (email, password)
                    VALUES (?, ?)
                    """,
                    (email, hashed_password)
                )

                conn.commit()

            flash("Registration successful! Please login.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash("This Gmail address is already registered.")

    return render_template("register.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.")

    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/")
@login_required
def index():

    return render_template("index.html")


# --------------------------------------------------
# NOTIFICATION INPUT VALIDATION
# --------------------------------------------------

def validate_notification_input(
    data: Any
) -> Tuple[bool, Optional[str]]:

    if not isinstance(data, dict):
        return False, "Request body must be a valid JSON object."

    email = data.get("email")
    subject = data.get("subject")
    message = data.get("message")

    if not email or not isinstance(email, str) or not email.strip():
        return False, "Recipient email is required."

    email = email.strip()

    if len(email) > 254:
        return False, "Email address exceeds maximum length."

    if not EMAIL_REGEX.match(email):
        return False, "Please enter a valid recipient email."

    if not subject or not isinstance(subject, str) or not subject.strip():
        return False, "Notification subject is required."

    subject = subject.strip()

    if len(subject) > 200:
        return False, "Subject cannot exceed 200 characters."

    if not message or not isinstance(message, str) or not message.strip():
        return False, "Notification message cannot be empty."

    message = message.strip()

    if len(message) > 5000:
        return False, "Message cannot exceed 5000 characters."

    return True, None


# --------------------------------------------------
# SEND NOTIFICATION
# --------------------------------------------------

@app.route("/send-notification", methods=["POST"])
@login_required
def send_notification():

    if not request.is_json:
        return jsonify({
            "success": False,
            "error": "Request must have Content-Type: application/json."
        }), 400

    data = request.get_json(silent=True)

    is_valid, error_msg = validate_notification_input(data)

    if not is_valid:
        return jsonify({
            "success": False,
            "error": error_msg
        }), 400

    email = data["email"].strip()
    subject = data["subject"].strip()
    message = data["message"].strip()

    redis_client = queue_service.get_redis_client()

    redis_online, redis_reason = queue_service.check_redis_health(
        redis_client
    )

    if not redis_online:
        return jsonify({
            "success": False,
            "error": (
                f"Redis is unreachable: {redis_reason}. "
                "Please start the Redis service."
            ),
            "redis_connected": False
        }), 503

    notification_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    try:

        database.insert_notification(
            notification_id=notification_id,
            email=email,
            subject=subject,
            message=message,
            status="PENDING",
            created_at=created_at
        )

        payload = {
            "id": notification_id,
            "email": email,
            "subject": subject,
            "message": message,
            "created_at": created_at
        }

        queue_service.push_notification_to_queue(
            payload,
            client=redis_client
        )

        return jsonify({
            "success": True,
            "message": "Notification successfully queued for delivery (Simulated).",
            "notification_id": notification_id,
            "status": "PENDING",
            "created_at": created_at
        }), 201

    except Exception as exc:

        try:
            database.update_notification_status(
                notification_id,
                status="FAILED",
                error=f"Queue submission failure: {str(exc)}"
            )
        except Exception:
            pass

        return jsonify({
            "success": False,
            "error": f"Failed to enqueue notification: {str(exc)}"
        }), 500


# --------------------------------------------------
# GET NOTIFICATION HISTORY
# --------------------------------------------------

@app.route("/notifications", methods=["GET"])
@login_required
def get_notifications():

    status_filter = request.args.get("status")
    search_query = request.args.get("search")

    try:

        limit = min(int(request.args.get("limit", 100)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)

    except ValueError:

        limit = 100
        offset = 0

    try:

        notifications = database.get_notifications(
            status=status_filter,
            search=search_query,
            limit=limit,
            offset=offset
        )

        counts = database.get_status_counts()
        queue_metrics = queue_service.get_queue_metrics()

        return jsonify({
            "success": True,
            "notifications": notifications,
            "counts": counts,
            "queue": queue_metrics,
            "total_records": len(notifications)
        }), 200

    except Exception as exc:

        return jsonify({
            "success": False,
            "error": f"Failed to retrieve notifications: {str(exc)}"
        }), 500


# --------------------------------------------------
# GET SINGLE NOTIFICATION
# --------------------------------------------------

@app.route("/notifications/<notification_id>", methods=["GET"])
@login_required
def get_single_notification(notification_id):

    record = database.get_notification_by_id(notification_id)

    if not record:
        return jsonify({
            "success": False,
            "error": "Notification not found."
        }), 404

    return jsonify({
        "success": True,
        "notification": record
    }), 200


# --------------------------------------------------
# RETRY NOTIFICATION
# --------------------------------------------------

@app.route("/retry-notification/<notification_id>", methods=["POST"])
@login_required
def retry_notification(notification_id):

    record = database.get_notification_by_id(notification_id)

    if not record:
        return jsonify({
            "success": False,
            "error": "Notification not found."
        }), 404

    redis_client = queue_service.get_redis_client()

    redis_online, redis_reason = queue_service.check_redis_health(
        redis_client
    )

    if not redis_online:
        return jsonify({
            "success": False,
            "error": f"Redis is unreachable: {redis_reason}"
        }), 503

    try:

        database.update_notification_status(
            notification_id,
            status="PENDING",
            error=None
        )

        payload = {
            "id": record["id"],
            "email": record["email"],
            "subject": record["subject"],
            "message": record["message"],
            "created_at": record["created_at"]
        }

        queue_service.push_notification_to_queue(
            payload,
            client=redis_client
        )

        return jsonify({
            "success": True,
            "message": (
                f"Notification {notification_id[:8]} "
                "re-enqueued for delivery."
            ),
            "notification_id": notification_id,
            "status": "PENDING"
        }), 200

    except Exception as exc:

        return jsonify({
            "success": False,
            "error": f"Failed to re-enqueue notification: {str(exc)}"
        }), 500


# --------------------------------------------------
# QUEUE STATUS
# --------------------------------------------------

@app.route("/queue-status", methods=["GET"])
@login_required
def queue_status():

    metrics = queue_service.get_queue_metrics()

    return jsonify({
        "success": True,
        "metrics": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/health", methods=["GET"])
def health_check():

    db_healthy = True
    db_msg = "Connected"

    try:

        with database.get_db_connection() as conn:
            conn.execute("SELECT 1;").fetchone()

    except Exception as exc:

        db_healthy = False
        db_msg = str(exc)

    redis_healthy, redis_msg = queue_service.check_redis_health()

    overall_status = (
        "healthy" if db_healthy and redis_healthy else "degraded"
    )

    return jsonify({
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": {
                "engine": "SQLite",
                "status": "connected" if db_healthy else "error",
                "details": db_msg,
                "file": database.get_db_path()
            },
            "message_queue": {
                "engine": "Redis",
                "status": "connected" if redis_healthy else "disconnected",
                "details": redis_msg,
                "host": queue_service.REDIS_HOST,
                "port": queue_service.REDIS_PORT
            }
        }
    }), 200 if db_healthy else 500


# --------------------------------------------------
# CLEAR NOTIFICATION HISTORY
# --------------------------------------------------

@app.route("/api/clear-history", methods=["POST"])
@login_required
def clear_history():

    try:

        deleted = database.clear_all_notifications()

        return jsonify({
            "success": True,
            "message": (
                f"Cleared {deleted} notification records from database."
            )
        }), 200

    except Exception as exc:

        return jsonify({
            "success": False,
            "error": str(exc)
        }), 500


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api") or request.is_json:
        return jsonify({
            "success": False,
            "error": "Requested resource was not found."
        }), 404

    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template("index.html"), 404


@app.errorhandler(405)
def method_not_allowed(error):

    return jsonify({
        "success": False,
        "error": "Method not allowed for this endpoint."
    }), 405


@app.errorhandler(500)
def internal_error(error):

    return jsonify({
        "success": False,
        "error": "Internal server error occurred."
    }), 500


# --------------------------------------------------
# RUN FLASK APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    debug = os.environ.get(
        "FLASK_DEBUG", "True"
    ).lower() in ("true", "1", "yes")

    print(
        f"[*] Starting Flask Server on "
        f"http://127.0.0.1:{port} (Debug={debug})..."
    )

    app.run(
        host="127.0.0.1",
        port=port,
        debug=debug
    )
