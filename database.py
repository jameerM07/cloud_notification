"""
Database Module for Cloud-Based Notification System.
Handles SQLite connection, schema initialization, and CRUD operations
with parameterized queries and WAL mode for high concurrency.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Default database filename
DEFAULT_DB_PATH = os.environ.get("DATABASE_PATH", "notifications.db")


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Return the active database file path."""
    return custom_path or os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Open a connection to SQLite database.
    Enables WAL mode and busy timeout for safe concurrent access by Flask and Worker.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row

    # Performance and concurrency optimizations
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """
    Initialize SQLite schema: creates notifications table and indexes.
    Safe to call multiple times (IF NOT EXISTS).
    """
    path = get_db_path(db_path)
    # Ensure directory exists if path contains directories
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with get_db_connection(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING', 'PROCESSING', 'SENT', 'FAILED')),
                created_at TEXT NOT NULL,
                sent_at TEXT,
                error TEXT
            );
            """
        )

        # Performance indexes for fast filtering and sorting
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);"
        )
        conn.commit()


def insert_notification(
    notification_id: str,
    email: str,
    subject: str,
    message: str,
    status: str = "PENDING",
    created_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Insert a newly accepted notification into SQLite.
    Status starts as PENDING.
    """
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO notifications (id, email, subject, message, status, created_at, sent_at, error)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL);
            """,
            (notification_id, email.strip(), subject.strip(), message.strip(), status, created_at),
        )
        conn.commit()

    return {
        "id": notification_id,
        "email": email.strip(),
        "subject": subject.strip(),
        "message": message.strip(),
        "status": status,
        "created_at": created_at,
        "sent_at": None,
        "error": None,
    }


def update_notification_status(
    notification_id: str,
    status: str,
    error: Optional[str] = None,
    sent_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """
    Update the status of a notification (PROCESSING, SENT, FAILED).
    Records sent_at timestamp upon completion, or error message upon failure.
    """
    valid_statuses = ("PENDING", "PROCESSING", "SENT", "FAILED")
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}")

    # Auto-generate sent_at if moving to SENT and no timestamp given
    if status == "SENT" and sent_at is None:
        sent_at = datetime.now(timezone.utc).isoformat()

    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE notifications
            SET status = ?, error = ?, sent_at = ?
            WHERE id = ?;
            """,
            (status, error, sent_at, notification_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_notification_by_id(
    notification_id: str, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve a single notification record by its unique ID."""
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM notifications WHERE id = ?;", (notification_id,)
        ).fetchone()
        return dict(row) if row else None


def get_notifications(
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve notification history, optionally filtered by status or search keyword (email/subject/id).
    Ordered by creation date descending.
    """
    query = "SELECT * FROM notifications WHERE 1=1"
    params: List[Any] = []

    if status and status.upper() != "ALL":
        query += " AND status = ?"
        params.append(status.upper())

    if search and search.strip():
        search_term = f"%{search.strip()}%"
        query += " AND (email LIKE ? OR subject LIKE ? OR id LIKE ?)"
        params.extend([search_term, search_term, search_term])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    with get_db_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_status_counts(db_path: Optional[str] = None) -> Dict[str, int]:
    """
    Calculate summary counts of notifications grouped by status.
    Returns: total, sent, pending, failed, processing
    """
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM notifications
            GROUP BY status;
            """
        ).fetchall()

        counts = {
            "total": 0,
            "sent": 0,
            "pending": 0,
            "failed": 0,
            "processing": 0,
        }

        for row in rows:
            st = row["status"].lower()
            cnt = row["count"]
            if st in counts:
                counts[st] = cnt
            counts["total"] += cnt

        return counts


def clear_all_notifications(db_path: Optional[str] = None) -> int:
    """Clear all notifications for demo reset purposes. Returns deleted count."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM notifications;")
        conn.commit()
        return cursor.rowcount


if __name__ == "__main__":
    print(f"Initializing database at '{get_db_path()}'...")
    init_db()
    print("Database initialized successfully.")
