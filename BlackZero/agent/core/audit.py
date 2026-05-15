"""
agent/core/audit.py — Capability health audit CLI for BlackZero v2 Third Pass.

Usage:
    python3 -m agent.core.audit
    python3 -m agent.core.audit --data-dir ~/.engineer0 --registry-dir registry/

Reads:
    evidence_results.jsonl   — tool execution history
    quarantine_overlay.json  — runtime quarantine state
    registry/capabilities/   — manifest metadata (lifecycle, kind)

Outputs a per-capability health table:
    CAPABILITY                 CALLS  OK   FAIL  RATE   QUARANTINE  LIFECYCLE
    tool.local.shell           14     11   3     78%    QUARANTINED active
    tool.local.read_file       22     22   0     100%   ok          active
    ...
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _load_manifests(registry_dir: Path) -> dict[str, dict]:
    """Return {capability_id: manifest} for all YAML files in registry/capabilities/."""
    manifests: dict[str, dict] = {}
    caps_dir = registry_dir / "capabilities"
    if not caps_dir.exists():
        return manifests
    for yaml_file in caps_dir.rglob("*.yaml"):
        try:
            m = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if m and "id" in m:
                manifests[m["id"]] = m
        except Exception:
            pass
    return manifests


def run_audit(data_dir: Path, registry_dir: Path) -> None:
    results   = _load_jsonl(data_dir / "evidence_results.jsonl")
    manifests = _load_manifests(registry_dir)

    qfile = data_dir / "quarantine_overlay.json"
    quarantine_state: dict[str, dict] = {}
    if qfile.exists():
        try:
            quarantine_state = json.loads(qfile.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Aggregate per capability.
    stats: dict[str, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "fail": 0, "last_error": ""})
    for rec in results:
        cap = rec.get("capability_id", "unknown")
        stats[cap]["calls"] += 1
        if rec.get("status") == "success":
            stats[cap]["ok"] += 1
        else:
            stats[cap]["fail"] += 1
            if rec.get("error"):
                stats[cap]["last_error"] = rec["error"][:80]

    # Merge in any quarantined capabilities not yet in evidence.
    for cap_id in quarantine_state:
        if cap_id not in stats:
            stats[cap_id]["calls"] = 0

    # Sort: quarantined first, then by failure count desc.
    def sort_key(item: tuple) -> tuple:
        cap_id, s = item
        is_q = quarantine_state.get(cap_id, {}).get("quarantined", False)
        return (not is_q, -s["fail"], cap_id)

    rows = sorted(stats.items(), key=sort_key)

    if not rows:
        print("No evidence data found.")
        return

    # Header
    col = 38
    print()
    print(f"{'CAPABILITY':<{col}} {'CALLS':>5}  {'OK':>4}  {'FAIL':>4}  {'RATE':>5}  "
          f"{'QUARANTINE':<12} {'LIFECYCLE'}")
    print("─" * (col + 52))

    for cap_id, s in rows:
        calls = s["calls"]
        ok    = s["ok"]
        fail  = s["fail"]
        rate  = f"{int(100 * ok / calls)}%" if calls else "—"
        q_entry     = quarantine_state.get(cap_id, {})
        is_quarantined = q_entry.get("quarantined", False)
        consec  = q_entry.get("consecutive_failures", 0)
        q_label = f"QUARANTINED({consec})" if is_quarantined else "ok"
        manifest  = manifests.get(cap_id, {})
        lifecycle = manifest.get("lifecycle", "—")
        print(
            f"{cap_id:<{col}} {calls:>5}  {ok:>4}  {fail:>4}  {rate:>5}  "
            f"{q_label:<12} {lifecycle}"
        )
        if is_quarantined and s["last_error"]:
            print(f"  {'':>{col}} last_error: {s['last_error']}")

    print()
    total_caps = len(rows)
    quarantined_count = sum(
        1 for cap_id, _ in rows
        if quarantine_state.get(cap_id, {}).get("quarantined", False)
    )
    print(f"Capabilities tracked: {total_caps}  |  Quarantined: {quarantined_count}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BlackZero capability health audit"
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Agent data directory (default: ~/.blackzero)",
    )
    parser.add_argument(
        "--registry-dir",
        default=None,
        help="Registry directory (default: registry/ relative to this file)",
    )
    args = parser.parse_args()

    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser()
    else:
        # Walk up to find the BlackZero root (contains registry/)
        here = Path(__file__).resolve()
        root = here.parent.parent.parent  # agent/core/ → agent/ → BlackZero/
        data_dir = Path("~/.blackzero").expanduser()
        # If running from inside an installed agent, prefer agent's own data dir.
        candidate = root / "data"
        if candidate.exists():
            data_dir = candidate

    if args.registry_dir:
        registry_dir = Path(args.registry_dir).expanduser()
    else:
        here = Path(__file__).resolve()
        registry_dir = here.parent.parent.parent / "registry"

    if not data_dir.exists():
        print(f"Data dir not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    run_audit(data_dir, registry_dir)


if __name__ == "__main__":
    main()
