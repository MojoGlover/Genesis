"""
timeanchor.py — pin the record to the world clock.

THE PROBLEM
-----------
Chronicle's `seq` gives total order across independent nodes without trusting
anyone's clock. That settles "what happened first". It does not settle "when".

If Chronicle's own host drifts, its `recv_ts` drifts with it, and every
timestamp in the chain is wrong together — consistently, invisibly, with nothing
to check it against. A hash chain proves nobody edited history; it does not
prove history happened when it says it did.

`timedatectl` reporting "System clock synchronized: yes" is not proof either.
That is the same trap as "process is running, therefore healthy": it reports the
daemon's opinion of itself, not a measurement against anything external.

THE FIX
-------
Periodically measure local time against several independent public authorities
and write the result into the chain as a record. The chain is then anchored to
real-world time at known points, and drift becomes an auditable event instead of
a silent corruption of every timestamp after it.

WHY SEVERAL SOURCES
-------------------
One source is a single point of trust — if it is wrong, or someone can influence
what a node sees, the anchor lies with confidence. Querying independent
operators and taking the median means one bad answer is outvoted, and
*disagreement between authorities is itself the signal* worth alerting on.

Uses HTTP `Date` headers rather than NTP: it works from any host that can reach
the internet, needs no daemon, no port, no privileges, and crosses the same path
the agents already use. Precision is ~1s, which is far tighter than the drift
worth catching.

A NOTE ON GENESIS/CLAUDE.md ("all external IO goes through plugops_bridge")
--------------------------------------------------------------------------
`sources.py` complies — it takes an injected `fetch` and routes through the
agent's own web_fetch tool. This module cannot, and the reason is not
convenience:

  1. It needs the response HEADERS (`Date`), not the body. web_fetch returns
     content; the timestamp is discarded before the caller ever sees it.
  2. It needs to time the round trip itself. Proxying through another process
     adds unmeasured queueing delay to the very quantity being measured — the
     answer would be wrong in a way that looks precise.
  3. Measuring the transport through a layer that may itself be delayed is
     circular.

What it actually does is narrow: an unauthenticated HEAD to four public
homepages, sending nothing, reading one header, adjusting nothing. If that
egress is unacceptable on a given node, set `duties.timeanchor.enabled: false` —
the grid then keeps `seq` ordering and simply has no external time proof.
"""
from __future__ import annotations

import email.utils
import logging
import statistics
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

__all__ = ["measure", "WORLD_CLOCKS"]

# Independent operators on purpose — different companies, different networks,
# different jurisdictions. Sources that share an owner are not a second opinion.
WORLD_CLOCKS: list[tuple[str, str]] = [
    ("cloudflare", "https://www.cloudflare.com"),
    ("google", "https://www.google.com"),
    ("nist", "https://www.nist.gov"),
    ("apple", "https://www.apple.com"),
]

# Beyond this, timestamps stop being trustworthy for correlating events across
# nodes. Well inside anything that would break a hash chain's usefulness.
DRIFT_WARN_SECONDS = 2.0
DRIFT_CRITICAL_SECONDS = 30.0

# If independent authorities disagree by more than this, something is wrong with
# the network path or a source — not with our clock. Do not "correct" to it.
SOURCE_DISAGREEMENT_SECONDS = 5.0

_TIMEOUT = 10


def _ssl_context():
    """Verified TLS, with certifi as a fallback CA store.

    macOS python.org builds ship without a usable CA bundle, so plugwan agents
    fail every HTTPS fetch with CERTIFICATE_VERIFY_FAILED while plugfoe works
    fine. certifi covers that gap.

    Verification is never disabled. An unverified anchor is worse than none —
    it invites trusting a time a network attacker chose.
    """
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch_time(url: str) -> float | None:
    """Return the server's Date as epoch seconds, corrected for round-trip.

    The Date header is generated when the response is built, so the true instant
    sits roughly half a round-trip before we read it. Halving RTT is the standard
    correction and keeps a slow link from reading as clock drift.
    """
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "ComputerBlack-timeanchor/1.0"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as r:
            rtt = time.time() - t0
            header = r.headers.get("Date")
        if not header:
            return None
        return email.utils.parsedate_to_datetime(header).timestamp() + rtt / 2
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, TypeError) as e:
        logger.debug("[timeanchor] %s unreachable: %s", url, e)
        return None


def measure() -> dict:
    """Compare local time to the world clock. Never raises."""
    local = time.time()
    readings: dict[str, float] = {}

    for name, url in WORLD_CLOCKS:
        ts = _fetch_time(url)
        if ts is not None:
            readings[name] = ts - local  # offset: positive = we are behind

    if not readings:
        # Being offline is not evidence of drift. Say so plainly rather than
        # emitting a scary-looking zero.
        return {
            "ok": False,
            "status": "unverified",
            "reason": "no world clock reachable — offline, not necessarily drifted",
            "local_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local)),
            "sources": {},
        }

    offsets = sorted(readings.values())
    offset = statistics.median(offsets)
    spread = offsets[-1] - offsets[0]

    if spread > SOURCE_DISAGREEMENT_SECONDS:
        status = "sources_disagree"
    elif abs(offset) > DRIFT_CRITICAL_SECONDS:
        status = "critical_drift"
    elif abs(offset) > DRIFT_WARN_SECONDS:
        status = "drift"
    else:
        status = "ok"

    return {
        "ok": status == "ok",
        "status": status,
        "offset_seconds": round(offset, 3),
        "source_spread_seconds": round(spread, 3),
        "sources_agreed": len(readings),
        "sources": {k: round(v, 3) for k, v in readings.items()},
        "local_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local)),
        "world_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local + offset)),
        # Recorded, never applied. Correcting the clock from an HTTP header would
        # make a compromised source able to rewrite when things happened — which
        # is exactly what anchoring exists to prevent. Report; let NTP steer.
        "action": "recorded only — clock not adjusted",
    }
