"""
Queue Service Module for Cloud-Based Notification System.
Provides Redis connection pooling, reliable queue operations (push, reliable pop,
acknowledgement), queue length metrics, and connection health checking.
"""

import json
import os
import sys
from typing import Any, Dict, Optional, Tuple
import redis
from dotenv import load_dotenv

load_dotenv()

# Redis Configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None
REDIS_URL = os.environ.get("REDIS_URL")

# Queue Name Configuration
NOTIFICATION_QUEUE = os.environ.get("NOTIFICATION_QUEUE", "notification_queue")
PROCESSING_QUEUE = os.environ.get("PROCESSING_QUEUE", "notification_processing_queue")


def get_redis_client(custom_client: Optional[redis.Redis] = None) -> redis.Redis:
    """
    Return a Redis client instance.
    Uses connection pooling and short socket timeout for fast failure detection.
    """
    if custom_client is not None:
        return custom_client

    if REDIS_URL:
        return redis.Redis.from_url(
            REDIS_URL,
            socket_timeout=3.0,
            socket_connect_timeout=3.0,
            decode_responses=True,
        )

    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        socket_timeout=3.0,
        socket_connect_timeout=3.0,
        decode_responses=True,
    )


def check_redis_health(client: Optional[redis.Redis] = None) -> Tuple[bool, str]:
    """
    Ping Redis server to determine connectivity.
    Returns (True, 'Connected') or (False, error_description).
    """
    try:
        r = client or get_redis_client()
        r.ping()
        return True, "Connected"
    except (redis.ConnectionError, redis.TimeoutError) as exc:
        return False, f"Redis unreachable on {REDIS_HOST}:{REDIS_PORT} ({type(exc).__name__})"
    except Exception as exc:
        return False, f"Redis error: {str(exc)}"


def push_notification_to_queue(
    payload: Dict[str, Any],
    client: Optional[redis.Redis] = None,
) -> bool:
    """
    Push a notification payload to the left side of the Redis queue (LPUSH).
    Worker pops from the right side (FIFO order).
    Raises redis.ConnectionError if Redis is down.
    """
    r = client or get_redis_client()
    serialized = json.dumps(payload)
    r.lpush(NOTIFICATION_QUEUE, serialized)
    return True


def pop_notification_reliably(
    timeout: int = 2,
    client: Optional[redis.Redis] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Atomically pop a task from NOTIFICATION_QUEUE and push to PROCESSING_QUEUE
    using RPOPLPUSH. This guarantees zero message loss if the worker crashes midway.
    Returns (raw_string, parsed_payload_dict) or None if timeout expired.
    """
    r = client or get_redis_client()
    raw = r.brpoplpush(NOTIFICATION_QUEUE, PROCESSING_QUEUE, timeout=timeout)
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        return raw, parsed
    except json.JSONDecodeError:
        # Malformed item; remove from processing and skip
        r.lrem(PROCESSING_QUEUE, 1, raw)
        return None


def acknowledge_notification(
    raw_payload: str,
    client: Optional[redis.Redis] = None,
) -> bool:
    """
    Remove the completed or handled notification from the PROCESSING_QUEUE (LREM).
    Called by worker once SQLite status is updated to SENT or FAILED.
    """
    r = client or get_redis_client()
    removed = r.lrem(PROCESSING_QUEUE, 1, raw_payload)
    return removed > 0


def recover_abandoned_tasks(client: Optional[redis.Redis] = None) -> int:
    """
    Worker recovery routine:
    Inspects PROCESSING_QUEUE on worker boot. Requeues any stranded items
    back to NOTIFICATION_QUEUE so they are not lost.
    Returns number of recovered items.
    """
    r = client or get_redis_client()
    recovered = 0
    while True:
        # Pop from processing queue and push back to main queue
        item = r.rpoplpush(PROCESSING_QUEUE, NOTIFICATION_QUEUE)
        if not item:
            break
        recovered += 1
    return recovered


def get_queue_metrics(client: Optional[redis.Redis] = None) -> Dict[str, Any]:
    """
    Fetch current lengths of both the primary queue and processing queue.
    """
    try:
        r = client or get_redis_client()
        waiting_count = r.llen(NOTIFICATION_QUEUE)
        processing_count = r.llen(PROCESSING_QUEUE)
        return {
            "connected": True,
            "waiting": waiting_count,
            "processing": processing_count,
            "total_queued": waiting_count + processing_count,
            "queue_name": NOTIFICATION_QUEUE,
        }
    except Exception as exc:
        return {
            "connected": False,
            "waiting": 0,
            "processing": 0,
            "total_queued": 0,
            "error": str(exc),
            "queue_name": NOTIFICATION_QUEUE,
        }
