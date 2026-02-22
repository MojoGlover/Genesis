"""
android_deploy/__main__.py
CLI entrypoint. Run as: python -m android_deploy [OPTIONS]

Usage examples:
  python -m android_deploy                          # build + deploy MadJanet
  python -m android_deploy --project madjanet       # explicit project
  python -m android_deploy --dry-run                # simulate, no writes
  python -m android_deploy --build-only             # build APK, skip deploy
  python -m android_deploy --deploy-only            # skip build, install existing APK
  python -m android_deploy --device Teklast         # target specific device by model
  python -m android_deploy --skip-bundle            # skip JS bundle (gradle only)
  python -m android_deploy --no-launch              # install but don't launch app
  python -m android_deploy --list                   # list registered projects
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .config import DEFAULT_PROJECT, get_project, list_projects
from .builder import build
from .deployer import deploy


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="android_deploy",
        description="Computer Black — Android APK builder and deployer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--project", "-p", default=DEFAULT_PROJECT,
                   help=f"Project key (default: {DEFAULT_PROJECT})")
    p.add_argument("--list", "-l", action="store_true",
                   help="List registered projects and exit")
    p.add_argument("--dry-run", "-n", action="store_true",
                   help="Print steps but don't execute any commands")
    p.add_argument("--build-only", action="store_true",
                   help="Build APK but don't deploy")
    p.add_argument("--deploy-only", action="store_true",
                   help="Skip build, deploy existing APK")
    p.add_argument("--skip-bundle", action="store_true",
                   help="Skip JS bundling step (use existing bundle)")
    p.add_argument("--device", "-d", default=None,
                   help="Target device serial or model name (auto-detect if omitted)")
    p.add_argument("--no-launch", action="store_true",
                   help="Install APK but don't launch the app")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.list:
        list_projects()
        sys.exit(0)

    try:
        project = get_project(args.project)
    except ValueError as e:
        print(f"\n  ✗ {e}")
        list_projects()
        sys.exit(1)

    print(f"\n  Computer Black — Android Deploy")
    print(f"  Project : {project.name}")
    print(f"  Root    : {project.root}")
    if args.dry_run:
        print(f"  Mode    : DRY RUN (no changes)")

    apk: Path | None = None

    # ── Build ──────────────────────────────────────────────────────────────────
    if not args.deploy_only:
        apk = build(project, dry_run=args.dry_run, skip_bundle=args.skip_bundle)
    else:
        # Use existing APK
        from pathlib import Path as _P
        apk = _P(project.root) / project.apk_path
        if not args.dry_run and not apk.exists():
            print(f"\n  ✗ No existing APK at: {apk}")
            print("    Run without --deploy-only to build first.")
            sys.exit(1)
        print(f"\n  → Using existing APK: {apk}")

    # ── Deploy ─────────────────────────────────────────────────────────────────
    if not args.build_only:
        deploy(
            apk=apk,
            project=project,
            device_hint=args.device,
            launch=not args.no_launch,
            dry_run=args.dry_run,
        )
    else:
        print("\n  → Deploy skipped (--build-only)")


if __name__ == "__main__":
    main()
