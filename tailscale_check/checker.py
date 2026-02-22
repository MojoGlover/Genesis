"""tailscale_check/checker.py — connectivity preflight."""
from __future__ import annotations
import json
import shutil
import socket
import subprocess
import sys
from typing import Optional

from .config import HOSTS, TIMEOUT_SECONDS


def get_tailscale_status() -> Optional[dict]:
    """Return parsed tailscale status JSON, or None if tailscale not installed."""
    if not shutil.which("tailscale"):
        return None
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def check_host(key: str) -> tuple[bool, str]:
    """
    Check if a host:port is reachable via TCP.
    Returns (reachable: bool, message: str).
    """
    cfg = HOSTS.get(key)
    if not cfg:
        return False, f"Unknown host key '{key}'"

    ip   = cfg["ip"]
    port = cfg["port"]
    try:
        with socket.create_connection((ip, port), timeout=TIMEOUT_SECONDS):
            return True, f"✓  {cfg['label']:30s} {ip}:{port}"
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return False, f"✗  {cfg['label']:30s} {ip}:{port}  ({type(e).__name__})"


def run_preflight(required_only: bool = False, verbose: bool = True) -> bool:
    """
    Run full preflight. Returns True if all required hosts pass.
    Prints results to stdout.
    """
    if verbose:
        print("\n  ── Tailscale Preflight ─────────────────────────────────────")

    # 1. Check tailscale daemon
    ts_status = get_tailscale_status()
    if ts_status is None:
        if verbose:
            print("  ⚠  tailscale CLI not found — skipping VPN check")
    else:
        backend = ts_status.get("BackendState", "unknown")
        color   = "✓" if backend == "Running" else "✗"
        if verbose:
            print(f"  {color}  Tailscale daemon: {backend}")

    # 2. Check all hosts
    all_passed   = True
    required_ok  = True

    keys = list(HOSTS.keys())
    if required_only:
        keys = [k for k, v in HOSTS.items() if v.get("required")]

    for key in keys:
        ok, msg = check_host(key)
        required = HOSTS[key].get("required", False)
        if not ok and required:
            required_ok = False
            all_passed  = False
        if not ok:
            all_passed = False
        if verbose:
            tag = " [required]" if required else ""
            print(f"  {msg}{tag}")

    if verbose:
        status = "PASS" if required_ok else "FAIL"
        print(f"\n  Preflight: {status}\n")

    return required_ok
