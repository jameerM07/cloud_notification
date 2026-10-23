"""
Redis Dev Server for Windows & Development Environments.
Runs an in-memory pure-Python Redis server over TCP on port 6379.
Ideal for college demos, Windows development, and environments where
native Redis or Docker cannot be installed.

Usage:
    python redis_dev_server.py [--port 6379] [--host 127.0.0.1]
"""

import argparse
import sys
import time

try:
    import fakeredis
except ImportError:
    print("[ERROR] 'fakeredis' is not installed. Run: pip install fakeredis")
    sys.exit(1)


def start_server(host: str = "127.0.0.1", port: int = 6379):
    print("=" * 65)
    print("  CLOUD-BASED NOTIFICATION SYSTEM — REDIS DEVELOPMENT SERVER")
    print("=" * 65)
    print(f"[*] Binding Redis TCP Server to {host}:{port}...")

    try:
        server = fakeredis.TcpFakeServer((host, port))
        print(f"[✓] Redis Server is RUNNING at {host}:{port}")
        print("[*] Compatible with standard Redis clients (redis-py, redis-cli)")
        print("[*] Ready to accept queue operations from Flask API & Worker.")
        print("[*] Press Ctrl+C at any time to shut down.")
        print("-" * 65)
        server.serve_forever()
    except OSError as err:
        if "address already in use" in str(err).lower() or getattr(err, "winerror", 0) == 10048:
            print(f"\n[!] Notice: Port {port} is already in use by an existing Redis service (Memurai, Docker, or native Redis).")
            print(f"[!] You already have a live Redis instance running on port {port}! You can proceed directly.")
        else:
            print(f"[ERROR] Failed to start Redis TCP server: {err}")
    except KeyboardInterrupt:
        print("\n[*] Shutting down Redis Dev Server... Goodbye!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run lightweight Redis Dev Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6379, help="Port (default: 6379)")
    args = parser.parse_args()

    start_server(args.host, args.port)
