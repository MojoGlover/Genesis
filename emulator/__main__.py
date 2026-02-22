"""
emulator/__main__.py — Android AVD manager CLI.

Usage:
    python -m emulator --list
    python -m emulator --start
    python -m emulator --start --name CB_Phone
    python -m emulator --stop
    python -m emulator --create --name CB_Tablet
    python -m emulator --wipe --name CB_Tablet
    python -m emulator --dry-run --start
"""
from __future__ import annotations
import argparse
import sys

from .config import DEFAULT_AVD, EMULATOR_CONFIG
from .manager import list_avds, start_avd, stop_avd, create_avd, wipe_avd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="emulator",
        description="Computer Black — Android emulator (AVD) manager",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list",   action="store_true", help="List all AVDs")
    g.add_argument("--start",  action="store_true", help="Start an AVD")
    g.add_argument("--stop",   action="store_true", help="Stop running emulator(s)")
    g.add_argument("--create", action="store_true", help="Create a new AVD from config profile")
    g.add_argument("--wipe",   action="store_true", help="Wipe AVD data (cold reset)")

    p.add_argument("--name", "-n", default=DEFAULT_AVD,
                   help=f"AVD name (default: {DEFAULT_AVD})")
    p.add_argument("--no-wait", action="store_true",
                   help="Don't wait for emulator to finish booting")
    p.add_argument("--dry-run", "-d", action="store_true",
                   help="Print steps, don't execute")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print("\n  Computer Black — Emulator Manager")

    if args.list:
        avds = list_avds()
        if avds:
            print(f"\n  AVDs ({len(avds)}):")
            for a in avds:
                profile = EMULATOR_CONFIG.get(a, {})
                desc = profile.get("description", "")
                print(f"    • {a:20s}  {desc}")
        else:
            print("\n  No AVDs found.")
            print("  Create one: python -m emulator --create --name CB_Tablet")
        return

    if args.start:
        start_avd(name=args.name, wait=not args.no_wait, dry_run=args.dry_run)

    elif args.stop:
        stop_avd(dry_run=args.dry_run)

    elif args.create:
        create_avd(name=args.name, dry_run=args.dry_run)

    elif args.wipe:
        wipe_avd(name=args.name, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
