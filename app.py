"""
Flask Application for Cloud-Based Notification System.
Provides REST API endpoints for submitting, monitoring, retrying, and tracking notifications,
with Redis message queuing and SQLite persistence.
"""

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

import database
import queue_service

load_dotenv()

# Basic RFC 5322 compliant email regex
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "college-cloud-notification-demo-key-2026")
# Limit max request body size to 1MB to prevent abuse
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

# Ensure SQLite schema is ready on boot
database.init_db()


def validate_notification_input(data: Any) -> Tuple[bool, Optional[str]]:
    """Validate incoming notification submission payload."""
    if not isinstance(data, dict):
        return False, "Request body must be a valid JSON object."

    email = data.get("email")
    subject = data.get("subject")
    message = data.get("message")

    # Recipient Email Validation
    if not email or not isinstance(email, str) or not email.strip():
        return False, "Recipient email is required."
    email = email.strip()
    if len(email) > 254:
        return False, "Email address exceeds maximum length of 254 characters."
    if not EMAIL_REGEX.match(email):
        return False, "Please enter a valid email address (e.g., user@example.com)."

    # Subject Validation
    if not subject or not isinstance(subject, str) or not subject.strip():
        return False, "Notification subject is required."
    subject = subject.strip()
    if len(subject) > 200:
        return False, "Subject cannot exceed 200 characters."

    # Message Validation
    if not message or not isinstance(message, str) or not message.strip():
        return False, "Notification message cannot be empty."
    message = message.strip()
    if len(message) > 5000:
        return False, "Message cannot exceed 5000 characters."

    return True, None


@app.route("/")
def index():
    """Serve the primary interactive dashboard."""
    return render_template("index.html")


@app.route("/send-notification", methods=["POST"])
def send_notification():
    """
    Accept, validate, persist, and queue a notification request.
    Steps:
    1. Validate input fields (email, subject, message).
    2. Check Redis connectivity.
    3. Save record to SQLite with status 'PENDING'.
    4. Enqueue into Redis queue.
    5. Return 201 Created on success, or appropriate error code.
    """
    if not request.is_json:
        return jsonify({
            "success": False,
            "error": "Request must have 'Content-Type: application/json'."
        }), 400

    data = request.get_json(silent=True)
    is_valid, error_msg = validate_notification_input(data)
    if not is_valid:
        return jsonify({"success": False, "error": error_msg}), 400

    email = data["email"].strip()
    subject = data["subject"].strip()
    message = data["message"].strip()

    # Pre-check Redis connectivity before database insertion
    # Requirement: "Do not report success if the notification could not be queued."
    redis_client = queue_service.get_redis_client()
    redis_online, redis_reason = queue_service.check_redis_health(redis_client)
    if not redis_online:
        return jsonify({
            "success": False,
            "error": f"Message queue (Redis) is currently unreachable. {redis_reason}. "
                     "Please ensure the Redis service or redis_dev_server.py is running.",
            "redis_connected": False
        }), 503

    notification_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        # Step 3: Insert into SQLite with status PENDING
        database.insert_notification(
            notification_id=notification_id,
            email=email,
            subject=subject,
            message=message,
            status="PENDING",
            created_at=created_at,
        )

        # Step 4: Add to Redis Queue
        payload = {
            "id": notification_id,
            "email": email,
            "subject": subject,
            "message": message,
            "created_at": created_at,
        }
        queue_service.push_notification_to_queue(payload, client=redis_client)

        return jsonify({
            "success": True,
            "message": "Notification successfully queued for delivery (Simulated).",
            "notification_id": notification_id,
            "status": "PENDING",
            "created_at": created_at,
        }), 201

    except Exception as exc:
        # Rollback SQLite record if queuing failed to avoid dangling pending records
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


@app.route("/notifications", methods=["GET"])
def get_notifications():
    """
    Return notification history, status counts, and queue statistics.
    Supports ?status=... &search=... &limit=... &offset=...
    """
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
            offset=offset,
        )
        counts = database.get_status_counts()
        queue_metrics = queue_service.get_queue_metrics()

        return jsonify({
            "success": True,
            "notifications": notifications,
            "counts": counts,
            "queue": queue_metrics,
            "total_records": len(notifications),
        }), 200
    except Exception as exc:
        return jsonify({
            "success": False,
            "error": f"Failed to retrieve notifications: {str(exc)}"
        }), 500


@app.route("/notifications/<notification_id>", methods=["GET"])
def get_single_notification(notification_id: str):
    """Retrieve detailed state of a single notification."""
    record = database.get_notification_by_id(notification_id)
    if not record:
        return jsonify({"success": False, "error": "Notification not found."}), 404

    return jsonify({"success": True, "notification": record}), 200


@app.route("/retry-notification/<notification_id>", methods=["POST"])
def retry_notification(notification_id: str):
    """
    Re-queue a failed notification for another delivery attempt.
    """
    record = database.get_notification_by_id(notification_id)
    if not record:
        return jsonify({"success": False, "error": "Notification not found."}), 404

    redis_client = queue_service.get_redis_client()
    redis_online, redis_reason = queue_service.check_redis_health(redis_client)
    if not redis_online:
        return jsonify({
            "success": False,
            "error": f"Redis message queue is unreachable ({redis_reason}). Cannot retry now."
        }), 503

    try:
        # Reset status to PENDING and clear previous error
        database.update_notification_status(notification_id, status="PENDING", error=None)

        payload = {
            "id": record["id"],
            "email": record["email"],
            "subject": record["subject"],
            "message": record["message"],
            "created_at": record["created_at"],
        }
        queue_service.push_notification_to_queue(payload, client=redis_client)

        return jsonify({
            "success": True,
            "message": f"Notification {notification_id[:8]}... re-enqueued for delivery.",
            "notification_id": notification_id,
            "status": "PENDING"
        }), 200
    except Exception as exc:
        return jsonify({
            "success": False,
            "error": f"Failed to re-enqueue notification: {str(exc)}"
        }), 500


@app.route("/queue-status", methods=["GET"])
def queue_status():
    """
    Return current Redis queue statistics:
    - waiting: items waiting in primary queue
    - processing: items currently in flight with workers
    - total_queued: waiting + processing
    - connected: boolean
    """
    metrics = queue_service.get_queue_metrics()
    return jsonify({
        "success": True,
        "metrics": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route("/health", methods=["GET"])
def health_check():
    """
    System health check returning database status, Redis queue status,
    and overall operational health.
    """
    # Check SQLite
    db_healthy = True
    db_msg = "Connected"
    try:
        with database.get_db_connection() as conn:
            conn.execute("SELECT 1;").fetchone()
    except Exception as exc:
        db_healthy = False
        db_msg = str(exc)

    # Check Redis
    redis_healthy, redis_msg = queue_service.check_redis_health()

    overall_status = "healthy" if (db_healthy and redis_healthy) else "degraded"

    return jsonify({
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": {
                "engine": "SQLite",
                "status": "connected" if db_healthy else "error",
                "details": db_msg,
                "file": database.get_db_path(),
            },
            "message_queue": {
                "engine": "Redis",
                "status": "connected" if redis_healthy else "disconnected",
                "details": redis_msg,
                "host": queue_service.REDIS_HOST,
                "port": queue_service.REDIS_PORT,
            },
        },
    }), 200 if db_healthy else 500


@app.route("/api/clear-history", methods=["POST"])
def clear_history():
    """Reset history for college demonstration purposes."""
    try:
        deleted = database.clear_all_notifications()
        return jsonify({
            "success": True,
            "message": f"Cleared {deleted} notification records from database."
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# Custom error handlers for clean JSON API responses
@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api") or request.is_json:
        return jsonify({"success": False, "error": "Requested resource was not found."}), 404
    return render_template("index.html"), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"success": False, "error": "Method not allowed for this endpoint."}), 405


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "Internal server error occurred."}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")
    print(f"[*] Starting Flask Server on http://127.0.0.1:{port} (Debug={debug})...")
    app.run(host="127.0.0.1", port=port, debug=debug)
