"""
Background Worker for Cloud-Based Notification System.
Processes notifications asynchronously from the Redis queue, updates SQLite state,
and simulates cloud email delivery with realistic lifecycle delays and failure simulation.

Runs as an independent background process in a separate terminal.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv

import database
import queue_service

load_dotenv()

# Simulation configuration
SIMULATION_DELAY_SECONDS = float(os.environ.get("SIMULATION_DELAY_SECONDS", "2.0"))
POLL_TIMEOUT_SECONDS = int(os.environ.get("POLL_TIMEOUT_SECONDS", "2"))

# ANSI escape codes for clean terminal outputs
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
RED = "\033[31m"
MAGENTA = "\033[35m"

running = True


def signal_handler(sig, frame):
    """Handle graceful shutdown on Ctrl+C (SIGINT) or SIGTERM."""
    global running
    print(f"\n{YELLOW}[WORKER] Graceful shutdown signal received. Finishing pending tasks...{RESET}")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def log(level: str, color: str, message: str):
    """Timestamped worker console logger."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{color}[{now}] [{level}] {message}{RESET}")


def process_notification(raw_payload: str, payload: Dict[str, Any]) -> bool:
    """
    Process a single notification:
    1. Update status to PROCESSING in SQLite.
    2. Simulate cloud delivery (delay + domain checks).
    3. Update status to SENT or FAILED in SQLite.
    4. Acknowledge and remove from Redis PROCESSING_QUEUE.
    """
    notification_id = payload.get("id")
    email = payload.get("email", "")
    subject = payload.get("subject", "")

    if not notification_id:
        log("ERROR", RED, f"Received notification missing 'id': {payload}")
        queue_service.acknowledge_notification(raw_payload)
        return False

    log("PICKED", CYAN, f"Processing Task ID={notification_id[:8]}... Recipient='{email}' Subject='{subject}'")

    # Step 1: Update status to PROCESSING in SQLite
    try:
        database.update_notification_status(notification_id, "PROCESSING")
        log("STATUS", BLUE, f"Notification ID={notification_id[:8]} -> PROCESSING")
    except Exception as db_err:
        log("ERROR", RED, f"Failed to update status to PROCESSING: {db_err}")

    # Step 2: Simulate cloud email delivery with realistic delay
    # Clearly labeled as SIMULATED as per requirements
    log("SIMULATE", MAGENTA, f"[SIMULATION] Connecting to Simulated Cloud Mail Dispatcher for '{email}'...")
    time.sleep(SIMULATION_DELAY_SECONDS)

    # Simulation check: allow demoing failure cases using known test emails or subject flags
    is_simulated_failure = False
    failure_reason = None

    lower_email = email.lower()
    lower_subject = subject.lower()

    if "fail" in lower_email or "error" in lower_email or "reject" in lower_email:
        is_simulated_failure = True
        failure_reason = "Simulated SMTP Error 550: Recipient mailbox rejected by target mail server."
    elif "[fail]" in lower_subject or "[error]" in lower_subject:
        is_simulated_failure = True
        failure_reason = "Simulated Dispatch Error: Upstream Cloud Mail Service timeout (Test trigger)."

    # Step 3: Update SQLite to SENT or FAILED
    if is_simulated_failure:
        log("FAILED", RED, f"[SIMULATION] Delivery failed for '{email}': {failure_reason}")
        database.update_notification_status(
            notification_id,
            status="FAILED",
            error=failure_reason,
        )
    else:
        sent_timestamp = datetime.now(timezone.utc).isoformat()
        database.update_notification_status(
            notification_id,
            status="SENT",
            sent_at=sent_timestamp,
        )
        log("SENT", GREEN, f"[SIMULATION] Notification ID={notification_id[:8]} successfully delivered to '{email}' (SIMULATED).")

    # Step 4: Acknowledge from Redis processing queue
    queue_service.acknowledge_notification(raw_payload)
    return not is_simulated_failure


def start_worker():
    """Main worker loop."""
    print("=" * 70)
    print(f"{BOLD}{CYAN}  CLOUD-BASED NOTIFICATION SYSTEM — BACKGROUND WORKER DAEMON{RESET}")
    print("=" * 70)
    print(f"[*] Database: {database.get_db_path()}")
    print(f"[*] Queue: {queue_service.NOTIFICATION_QUEUE}")
    print(f"[*] Processing Queue: {queue_service.PROCESSING_QUEUE}")
    print(f"[*] Simulated Delivery Delay: {SIMULATION_DELAY_SECONDS}s")
    print(f"{YELLOW}[*] NOTICE: All email transmissions are SIMULATED for demonstration.{RESET}")
    print("-" * 70)

    # Initialize SQLite database schema if not present
    database.init_db()

    # Health check for Redis
    client = queue_service.get_redis_client()
    connected, reason = queue_service.check_redis_health(client)
    if not connected:
        log("WARN", YELLOW, f"Redis not connected: {reason}")
        log("WARN", YELLOW, "Worker will poll and attempt reconnection automatically...")
    else:
        log("INIT", GREEN, "Connected to Redis successfully.")
        # Recover any orphaned tasks from previous worker crashes
        recovered = queue_service.recover_abandoned_tasks(client)
        if recovered > 0:
            log("RECOVER", YELLOW, f"Recovered {recovered} unacknowledged task(s) from previous session.")

    log("READY", GREEN, "Worker is ready and listening for incoming notification requests...")

    idle_count = 0
    while running:
        try:
            # Reliable atomic pop from Redis
            task = queue_service.pop_notification_reliably(timeout=POLL_TIMEOUT_SECONDS, client=client)

            if task is not None:
                idle_count = 0
                raw_payload, parsed_payload = task
                process_notification(raw_payload, parsed_payload)
            else:
                idle_count += 1
                if idle_count % 15 == 0:
                    metrics = queue_service.get_queue_metrics(client)
                    if metrics.get("connected"):
                        log("IDLE", BLUE, f"Worker active | Queue depth: {metrics['waiting']} waiting, {metrics['processing']} processing.")
                    else:
                        log("WARN", YELLOW, "Waiting for Redis connection to resume...")

        except Exception as exc:
            if not running:
                break
            log("ERROR", RED, f"Worker loop error: {exc}")
            time.sleep(2.0)

    print(f"{GREEN}[WORKER] Worker has shut down cleanly.{RESET}")


if __name__ == "__main__":
    start_worker()
