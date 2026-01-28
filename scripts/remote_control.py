#!/usr/bin/env python3
"""
GENESIS Remote Control — Watches iCloud folder for commands from iPhone.

Commands (create file with this name):
  start-genesis     → Start Tailscale + GENESIS server
  stop-genesis      → Stop the server
  status            → Write current status to iCloud

Responses written to: ~/iCloud/genesis-remote/status.txt
"""

import os
import subprocess
import time
from pathlib import Path
from datetime import datetime

# iCloud folder path
ICLOUD_FOLDER = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/genesis-remote"
GENESIS_DIR = Path.home() / "ai/GENESIS"
STATUS_FILE = ICLOUD_FOLDER / "status.txt"
PID_FILE = Path("/tmp/genesis-server.pid")

# Full paths for LaunchAgent (no PATH inheritance)
TAILSCALE = "/opt/homebrew/bin/tailscale"
UVICORN = "/Library/Frameworks/Python.framework/Versions/3.11/bin/uvicorn"


def write_status(message: str):
    """Write status to iCloud so iPhone can read it."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATUS_FILE.write_text(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}")


def get_tailscale_ip() -> str:
    """Get Tailscale IP address."""
    try:
        result = subprocess.run(
            [TAILSCALE, "ip", "-4"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def is_server_running() -> bool:
    """Check if GENESIS server is running."""
    try:
        result = subprocess.run(
            ["lsof", "-ti:8000"],
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def start_tailscale():
    """Ensure Tailscale is running."""
    try:
        # Check if already connected
        result = subprocess.run(
            [TAILSCALE, "status"],
            capture_output=True, text=True, timeout=10
        )
        if "Tailscale is stopped" in result.stdout or result.returncode != 0:
            subprocess.run([TAILSCALE, "up"], timeout=30)
            time.sleep(2)
    except Exception as e:
        write_status(f"Tailscale error: {e}")


def start_server():
    """Start GENESIS server."""
    if is_server_running():
        ip = get_tailscale_ip()
        write_status(f"Server already running at http://{ip}:8000")
        return

    # Start Tailscale first
    start_tailscale()

    # Start server
    os.chdir(GENESIS_DIR)
    process = subprocess.Popen(
        [UVICORN, "app:app", "--host", "0.0.0.0", "--port", "8000"],
        stdout=open("/tmp/genesis-server.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )

    # Save PID
    PID_FILE.write_text(str(process.pid))

    # Wait for server to be ready
    time.sleep(5)

    if is_server_running():
        ip = get_tailscale_ip()
        write_status(f"Server started at http://{ip}:8000")
    else:
        write_status("Server failed to start. Check /tmp/genesis-server.log")


def stop_server():
    """Stop GENESIS server."""
    try:
        result = subprocess.run(
            ["lsof", "-ti:8000"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            subprocess.run(["kill", "-9", pid])

        write_status("Server stopped")
    except Exception as e:
        write_status(f"Stop error: {e}")


def get_status():
    """Write current status to iCloud."""
    running = is_server_running()
    ip = get_tailscale_ip()

    if running:
        write_status(f"Server running at http://{ip}:8000")
    else:
        write_status(f"Server stopped. Tailscale IP: {ip}")


def process_command(cmd_file: Path):
    """Process a command file."""
    cmd = cmd_file.stem.lower()

    if cmd == "start-genesis":
        start_server()
    elif cmd == "stop-genesis":
        stop_server()
    elif cmd == "status":
        get_status()
    else:
        write_status(f"Unknown command: {cmd}")

    # Remove the command file
    try:
        cmd_file.unlink()
    except Exception:
        pass


def watch_folder():
    """Watch iCloud folder for command files."""
    print(f"Watching {ICLOUD_FOLDER} for commands...")
    write_status("Remote control ready. Drop a command file to trigger.")

    seen = set()

    while True:
        try:
            # Check for new files
            for f in ICLOUD_FOLDER.iterdir():
                if f.name.startswith(".") or f.name == "status.txt":
                    continue

                if f.name not in seen:
                    seen.add(f.name)
                    print(f"Found command: {f.name}")
                    process_command(f)
                    seen.discard(f.name)

            time.sleep(2)  # Check every 2 seconds

        except KeyboardInterrupt:
            print("\nStopping watcher...")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Direct command mode
        cmd = sys.argv[1]
        if cmd == "start":
            start_server()
        elif cmd == "stop":
            stop_server()
        elif cmd == "status":
            get_status()
        elif cmd == "watch":
            watch_folder()
        else:
            print(f"Usage: {sys.argv[0]} [start|stop|status|watch]")
    else:
        # Default: watch mode
        watch_folder()
