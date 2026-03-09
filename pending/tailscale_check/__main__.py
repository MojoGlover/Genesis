"""
tailscale_check/__main__.py — Tailscale preflight CLI.

Usage:
    python -m tailscale_check              # full preflight, all hosts
    python -m tailscale_check --required   # only required hosts
    python -m tailscale_check --host ollama
    python -m tailscale_check --status     # tailscale daemon status only
    python -m tailscale_check --list       # list configured hosts
"""
from __future__ import annotations
import argparse
import sys

from .config import HOSTS
from .checker import run_preflight, check_host, get_tailscale_status


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tailscale_check",
        description="Computer Black — Tailscale connectivity preflight",
    )
    p.add_argument("--host", "-H", default=None,
                   help="Check a single host by key (e.g. ollama, mac)")
    p.add_argument("--required", "-r", action="store_true",
                   help="Only check required hosts")
    p.add_argument("--status", "-s", action="store_true",
                   help="Show Tailscale daemon status and exit")
    p.add_argument("--list", "-l", action="store_true",
                   help="List configured hosts and exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print("\n  Computer Black — Tailscale Check")

    if args.list:
        print(f"\n  {'Key':15s} {'Label':30s} {'IP':20s} {'Port':6s} Required")
        print(f"  {'-'*15} {'-'*30} {'-'*20} {'-'*6} --------")
        for key, cfg in HOSTS.items():
            req = "yes" if cfg.get("required") else "no"
            print(f"  {key:15s} {cfg['label']:30s} {cfg['ip']:20s} {cfg['port']:<6} {req}")
        print()
        return

    if args.status:
        ts = get_tailscale_status()
        if ts is None:
            print("  ✗ tailscale not installed or not in PATH")
        else:
            print(f"  Backend: {ts.get('BackendState')}")
            print(f"  Self:    {ts.get('Self', {}).get('DNSName', '—')}")
        return

    if args.host:
        ok, msg = check_host(args.host)
        print(f"\n  {msg}\n")
        sys.exit(0 if ok else 1)

    ok = run_preflight(required_only=args.required)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
