"""
ios_deploy/__main__.py — iOS build and deploy CLI.

Usage:
    python -m ios_deploy --build                     # EAS cloud build
    python -m ios_deploy --build --profile preview
    python -m ios_deploy --testflight                # submit to TestFlight
    python -m ios_deploy --sideload                  # sideload instructions
    python -m ios_deploy --sideload --method sideloadly --ipa ~/Downloads/app.ipa
    python -m ios_deploy --dry-run --build
"""
from __future__ import annotations
import argparse

from .config import IOS_CONFIG, SIDELOAD_METHODS
from .builder import build_ios, submit_testflight, sideload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ios_deploy",
        description="Computer Black — iOS build and deploy",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--build",       action="store_true", help="Trigger EAS iOS build")
    g.add_argument("--testflight",  action="store_true", help="Submit to TestFlight")
    g.add_argument("--sideload",    action="store_true", help="Sideload via AltServer/Sideloadly")
    g.add_argument("--info",        action="store_true", help="Show iOS deploy info and requirements")

    p.add_argument("--project",  "-p", default="madjanet",
                   choices=list(IOS_CONFIG.keys()))
    p.add_argument("--profile",  default="preview",
                   help="EAS build profile (default: preview)")
    p.add_argument("--url",      default="",
                   help="Build artifact URL for TestFlight submit")
    p.add_argument("--ipa",      default="",
                   help="Local IPA path for sideload")
    p.add_argument("--method",   default="altserver",
                   choices=list(SIDELOAD_METHODS.keys()),
                   help="Sideload method (default: altserver)")
    p.add_argument("--dry-run",  "-n", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print("\n  Computer Black — iOS Deploy")

    if args.info:
        cfg = IOS_CONFIG.get(args.project, {})
        print(f"\n  Project     : {cfg.get('display_name', args.project)}")
        print(f"  Bundle ID   : {cfg.get('bundle_id', '—')}")
        print(f"  Team ID     : {cfg.get('team_id') or '⚠  not set (Apple Dev account needed)'}")
        print(f"  Apple ID    : {cfg.get('apple_id') or '⚠  not set'}")
        print(f"\n  Free options (no Dev account):")
        for k, v in SIDELOAD_METHODS.items():
            print(f"    {k:12s}  {v['description']}")
        print()
        return

    if args.build:
        build_ios(args.project, profile=args.profile, dry_run=args.dry_run)

    elif args.testflight:
        submit_testflight(args.project, build_url=args.url, dry_run=args.dry_run)

    elif args.sideload:
        sideload(args.project, ipa_path=args.ipa, method=args.method, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
