"""
clock.py — is this node's clock trustworthy?

Reads what NTP already measured. No network calls, no external egress, nothing
to grant an exception for.

WHY THIS REPLACED AN EARLIER VERSION
------------------------------------
The first attempt fetched HTTP `Date` headers from four websites and compared
them to local time. On plugfoe it reported the clock was **0.695 seconds** off.
NTP, already running on the same box, measured the real offset at **+108
microseconds** — the module was ~6,400x less precise and was reporting drift
that did not exist. Almost all of what it "detected" was HTTP round-trip noise.

Darnie caught it by asking "is this the best way, or should we just make the
exception?" — without knowing what a stratum-2 server is. The answer was that
NTP already solved it, better, locally, and the exception was never needed.

The lesson is now question one of the change checklist: **what already does
this?** Ask the machine before writing code to find out.

WHAT THIS DOES AND DOES NOT CLAIM
---------------------------------
It reports whether the clock is disciplined and by how much it is off — that is
time *synchronization*, and NTP owns it.

It does not prove a record existed at a claimed time. That is *attestation*, a
different problem, and the right tool is RFC 3161 timestamping: send a hash of
Chronicle's chain head to a Time Stamping Authority and keep the signed token.
An unsigned number from any source — including this one — proves nothing about
the past. Not built; recorded here so the gap is known rather than assumed
covered.
"""
from __future__ import annotations

import re
import subprocess

__all__ = ["measure", "DRIFT_WARN_SECONDS"]

# Beyond this, timestamps stop being reliable for correlating events across
# nodes. Enormously loose compared to NTP's normal sub-millisecond discipline —
# crossing it means something is actually wrong, not merely imprecise.
DRIFT_WARN_SECONDS = 1.0
DRIFT_CRITICAL_SECONDS = 30.0

_UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}


def _to_seconds(value: str) -> float | None:
    """'+108us' → 0.000108. NTP tools report in mixed units."""
    m = re.match(r"([+-]?[\d.]+)\s*(ns|us|µs|ms|s)?", value.strip())
    if not m:
        return None
    try:
        return float(m.group(1)) * _UNITS.get(m.group(2) or "s", 1.0)
    except ValueError:
        return None


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout or ""
    except Exception:  # noqa: BLE001 — absence of a tool is not an error here
        return ""


def _timedatectl() -> dict | None:
    show = _run(["timedatectl", "show"])
    if not show:
        return None
    fields = dict(
        line.split("=", 1) for line in show.splitlines() if "=" in line
    )
    synced = fields.get("NTPSynchronized", "").lower() == "yes"

    offset = jitter = None
    server = ""
    for line in _run(["timedatectl", "timesync-status"]).splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "offset":
            offset = _to_seconds(val)
        elif key == "jitter":
            jitter = _to_seconds(val)
        elif key == "server":
            server = val

    return {"source": "systemd-timesyncd", "synchronized": synced,
            "offset_seconds": offset, "jitter_seconds": jitter, "server": server}


def _chrony() -> dict | None:
    out = _run(["chronyc", "tracking"])
    if not out:
        return None
    offset = jitter = None
    server = ""
    for line in out.splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "last offset":
            offset = _to_seconds(val.replace("seconds", ""))
        elif key == "rms offset":
            jitter = _to_seconds(val.replace("seconds", ""))
        elif key == "reference id":
            server = val
    return {"source": "chrony", "synchronized": offset is not None,
            "offset_seconds": offset, "jitter_seconds": jitter, "server": server}


def _macos_sntp() -> dict | None:
    """macOS has neither chrony nor timesyncd; `sntp` queries without sudo.

    Output: '+2.029378 +/- 0.011265 time.apple.com 17.253.6.45'
    That is a real NTP exchange — same protocol, same precision class as the
    Linux daemons — not an HTTP header. Agents run on plugwan too, so a clock
    duty that only worked on Linux would silently never report there.
    """
    out = _run(["sntp", "time.apple.com"]).strip()
    if not out:
        return None
    m = re.match(r"([+-][\d.]+)\s*\+/-\s*([\d.]+)\s+(\S+)", out)
    if not m:
        return None
    return {"source": "sntp", "synchronized": True,
            "offset_seconds": float(m.group(1)),
            "jitter_seconds": float(m.group(2)),
            "server": m.group(3)}


def measure() -> dict:
    """Report the clock's discipline. Never raises."""
    reading = _chrony() or _timedatectl() or _macos_sntp()

    if reading is None:
        # No NTP client. Say exactly that — do not imply the clock is fine, and
        # do not invent a measurement to fill the gap.
        return {"ok": False, "status": "no_ntp_client",
                "detail": "no chrony or systemd-timesyncd — clock is undisciplined",
                "offset_seconds": None}

    offset = reading.get("offset_seconds")

    if not reading.get("synchronized"):
        status = "not_synchronized"
    elif offset is None:
        status = "synchronized_no_offset"
    elif abs(offset) > DRIFT_CRITICAL_SECONDS:
        status = "critical_drift"
    elif abs(offset) > DRIFT_WARN_SECONDS:
        status = "drift"
    else:
        status = "ok"

    return {"ok": status == "ok", "status": status, **reading,
            "attestation": "none — offset proves sync, not that a record "
                           "existed at a claimed time (see module docstring)"}
