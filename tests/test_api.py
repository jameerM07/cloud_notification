"""
Automated Test Suite for Cloud-Based Notification System.
Tests Flask REST API endpoints, input validation, SQLite persistence,
Redis queue integration, worker execution, and error handling.
"""

import json
import os
import tempfile
import pytest
import fakeredis

# Set testing environment before importing app
os.environ["DATABASE_PATH"] = ":memory:"

import app as flask_app
import database
import queue_service
import worker


@pytest.fixture
def test_setup():
    """Configure a temporary SQLite database and fake Redis instance for tests."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    os.environ["DATABASE_PATH"] = db_path
    database.init_db(db_path)

    # Set up fake Redis client
    fake_redis_client = fakeredis.FakeRedis(decode_responses=True)

    # Patch queue_service to use fake_redis_client
    original_get_client = queue_service.get_redis_client
    queue_service.get_redis_client = lambda custom_client=None: custom_client or fake_redis_client

    flask_app.app.config["TESTING"] = True
    client = flask_app.app.test_client()

    yield {
        "client": client,
        "db_path": db_path,
        "fake_redis": fake_redis_client,
    }

    # Teardown
    queue_service.get_redis_client = original_get_client
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


def test_index_dashboard(test_setup):
    """Test that GET / returns the HTML dashboard."""
    client = test_setup["client"]
    response = client.get("/")
    assert response.status_code == 200
    assert b"CloudNotify" in response.data or b"Notification" in response.data


def test_health_check_endpoint(test_setup):
    """Test GET /health returns service health."""
    client = test_setup["client"]
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert "status" in data
    assert "services" in data
    assert data["services"]["database"]["status"] == "connected"
    assert data["services"]["message_queue"]["status"] == "connected"


def test_send_notification_valid(test_setup):
    """Test valid notification submission via POST /send-notification."""
    client = test_setup["client"]
    payload = {
        "email": "student@college.edu",
        "subject": "Cloud Lab Assignment Graded",
        "message": "Your submission for Cloud Project 1 has received an A grade.",
    }
    response = client.post(
        "/send-notification",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["success"] is True
    assert data["status"] == "PENDING"
    assert "notification_id" in data

    # Verify notification exists in SQLite
    stored = database.get_notification_by_id(data["notification_id"], test_setup["db_path"])
    assert stored is not None
    assert stored["email"] == "student@college.edu"
    assert stored["status"] == "PENDING"

    # Verify notification was queued in Redis
    fake_redis = test_setup["fake_redis"]
    queue_len = fake_redis.llen(queue_service.NOTIFICATION_QUEUE)
    assert queue_len == 1


def test_send_notification_missing_fields(test_setup):
    """Test validation errors for missing or empty fields."""
    client = test_setup["client"]

    # Missing email
    r1 = client.post(
        "/send-notification",
        data=json.dumps({"subject": "Hello", "message": "World"}),
        content_type="application/json",
    )
    assert r1.status_code == 400
    assert "email is required" in r1.get_json()["error"].lower()

    # Missing subject
    r2 = client.post(
        "/send-notification",
        data=json.dumps({"email": "valid@email.com", "message": "World"}),
        content_type="application/json",
    )
    assert r2.status_code == 400
    assert "subject is required" in r2.get_json()["error"].lower()

    # Missing message
    r3 = client.post(
        "/send-notification",
        data=json.dumps({"email": "valid@email.com", "subject": "Hello"}),
        content_type="application/json",
    )
    assert r3.status_code == 400
    assert "message cannot be empty" in r3.get_json()["error"].lower()


def test_send_notification_invalid_email(test_setup):
    """Test rejection of malformed email addresses."""
    client = test_setup["client"]
    invalid_emails = ["not-an-email", "missing@domain", "@missinguser.com", "spaces in@email.com"]
    for bad_email in invalid_emails:
        res = client.post(
            "/send-notification",
            data=json.dumps({
                "email": bad_email,
                "subject": "Test",
                "message": "Testing invalid email formats"
            }),
            content_type="application/json",
        )
        assert res.status_code == 400
        assert "valid email" in res.get_json()["error"].lower()


def test_get_notifications_and_counts(test_setup):
    """Test GET /notifications history, counts, and search filter."""
    client = test_setup["client"]
    db_path = test_setup["db_path"]

    # Insert 3 test notifications
    database.insert_notification("id-1", "alice@example.com", "Welcome Alice", "Msg 1", "SENT", db_path=db_path)
    database.insert_notification("id-2", "bob@example.com", "Alert Bob", "Msg 2", "PENDING", db_path=db_path)
    database.insert_notification("id-3", "charlie@fail.com", "Warning Charlie", "Msg 3", "FAILED", db_path=db_path)

    # Fetch all
    res = client.get("/notifications")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["notifications"]) == 3
    assert data["counts"]["total"] == 3
    assert data["counts"]["sent"] == 1
    assert data["counts"]["pending"] == 1
    assert data["counts"]["failed"] == 1

    # Filter by status: SENT
    res_sent = client.get("/notifications?status=SENT")
    data_sent = res_sent.get_json()
    assert len(data_sent["notifications"]) == 1
    assert data_sent["notifications"][0]["email"] == "alice@example.com"

    # Search by keyword: 'Bob'
    res_search = client.get("/notifications?search=Bob")
    data_search = res_search.get_json()
    assert len(data_search["notifications"]) == 1
    assert data_search["notifications"][0]["id"] == "id-2"


def test_queue_status_endpoint(test_setup):
    """Test GET /queue-status reflects Redis state."""
    client = test_setup["client"]
    res = client.get("/queue-status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "metrics" in data
    assert data["metrics"]["connected"] is True
    assert data["metrics"]["waiting"] == 0


def test_retry_failed_notification(test_setup):
    """Test POST /retry-notification/<id> re-enqueues failed task."""
    client = test_setup["client"]
    db_path = test_setup["db_path"]
    fake_redis = test_setup["fake_redis"]

    # Insert a failed notification
    database.insert_notification(
        "failed-id-123",
        "retry_user@example.com",
        "Failed Message",
        "Need retry",
        status="FAILED",
        db_path=db_path,
    )
    database.update_notification_status("failed-id-123", "FAILED", error="Previous timeout", db_path=db_path)

    # Call retry
    res = client.post("/retry-notification/failed-id-123")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "PENDING"

    # Verify status in database is reset to PENDING and error cleared
    updated = database.get_notification_by_id("failed-id-123", db_path)
    assert updated["status"] == "PENDING"
    assert updated["error"] is None

    # Verify item was pushed into Redis queue
    assert fake_redis.llen(queue_service.NOTIFICATION_QUEUE) == 1


def test_redis_down_returns_503(test_setup):
    """Test graceful handling when Redis is unavailable during send."""
    client = test_setup["client"]

    # Simulate Redis connection failure
    def mock_broken_client(custom_client=None):
        class BrokenRedis:
            def ping(self):
                import redis
                raise redis.ConnectionError("Simulated Redis Connection Refused")
        return BrokenRedis()

    original_client_fn = queue_service.get_redis_client
    queue_service.get_redis_client = mock_broken_client

    try:
        res = client.post(
            "/send-notification",
            data=json.dumps({
                "email": "test@example.com",
                "subject": "Test when redis down",
                "message": "Should receive 503 error"
            }),
            content_type="application/json",
        )
        assert res.status_code == 503
        data = res.get_json()
        assert data["success"] is False
        assert "unreachable" in data["error"].lower()
    finally:
        queue_service.get_redis_client = original_client_fn


def test_worker_processing_success(test_setup):
    """Test worker processing flow: PENDING -> PROCESSING -> SENT (simulated)."""
    db_path = test_setup["db_path"]
    fake_redis = test_setup["fake_redis"]

    # Insert a pending notification
    notif = database.insert_notification(
        "worker-test-1",
        "student@college.edu",
        "Lab Complete",
        "Your project is verified",
        status="PENDING",
        db_path=db_path
    )
    raw_payload = json.dumps(notif)
    fake_redis.lpush(queue_service.PROCESSING_QUEUE, raw_payload)

    original_delay = worker.SIMULATION_DELAY_SECONDS
    worker.SIMULATION_DELAY_SECONDS = 0.01
    try:
        success = worker.process_notification(raw_payload, notif)
        assert success is True

        # Check that database updated to SENT
        record = database.get_notification_by_id("worker-test-1", db_path)
        assert record["status"] == "SENT"
        assert record["sent_at"] is not None
        assert record["error"] is None

        # Check that it was acknowledged and removed from Redis processing queue
        assert fake_redis.llen(queue_service.PROCESSING_QUEUE) == 0
    finally:
        worker.SIMULATION_DELAY_SECONDS = original_delay


def test_worker_processing_failure(test_setup):
    """Test worker failure handling when email triggers simulated error."""
    db_path = test_setup["db_path"]
    fake_redis = test_setup["fake_redis"]

    notif = database.insert_notification(
        "worker-test-fail-1",
        "fail-user@test.com",
        "Simulate Failure Test",
        "Should trigger simulated failure",
        status="PENDING",
        db_path=db_path
    )
    raw_payload = json.dumps(notif)
    fake_redis.lpush(queue_service.PROCESSING_QUEUE, raw_payload)

    original_delay = worker.SIMULATION_DELAY_SECONDS
    worker.SIMULATION_DELAY_SECONDS = 0.01
    try:
        success = worker.process_notification(raw_payload, notif)
        assert success is False

        # Database should show FAILED status and error reason
        record = database.get_notification_by_id("worker-test-fail-1", db_path)
        assert record["status"] == "FAILED"
        assert record["sent_at"] is None
        assert "Simulated SMTP Error" in record["error"]

        # Acknowledged and removed from processing queue
        assert fake_redis.llen(queue_service.PROCESSING_QUEUE) == 0
    finally:
        worker.SIMULATION_DELAY_SECONDS = original_delay


def test_empty_history_and_clear(test_setup):
    """Test empty notifications state and clear history API."""
    client = test_setup["client"]
    db_path = test_setup["db_path"]

    # Ensure empty
    database.clear_all_notifications(db_path)
    res = client.get("/notifications")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["notifications"]) == 0
    assert data["counts"]["total"] == 0

    # Insert one, then call clear-history API
    database.insert_notification("id-del", "del@test.com", "Test", "Test", db_path=db_path)
    res_clear = client.post("/api/clear-history")
    assert res_clear.status_code == 200
    assert res_clear.get_json()["success"] is True

    # Re-verify empty
    res_after = client.get("/notifications")
    assert len(res_after.get_json()["notifications"]) == 0
