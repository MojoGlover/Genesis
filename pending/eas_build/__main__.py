"""
eas_build/__main__.py — EAS cloud build CLI.

Usage:
    python -m eas_build --platform android --profile preview
    python -m eas_build --platform ios --profile preview
    python -m eas_build --status
    python -m eas_build --download https://expo.dev/artifacts/...
    python -m eas_build --dry-run --platform android
"""
from __future__ import annotations
import argparse

from .config import EAS_CONFIG, PROFILES, DEFAULT_PROFILE
from .builder import trigger_build, get_build_status, download_artifact


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="eas_build",
        description="Computer Black — EAS cloud build manager",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--build",    action="store_true", help="Trigger a cloud build")
    g.add_argument("--status",   action="store_true", help="Show recent build status")
    g.add_argument("--download", metavar="URL",       help="Download a build artifact by URL")
    g.add_argument("--profiles", action="store_true", help="List available build profiles")

    p.add_argument("--project",  "-p", default="madjanet",
                   choices=list(EAS_CONFIG.keys()),
                   help="Project key (default: madjanet)")
    p.add_argument("--platform", default="android",
                   choices=["android", "ios", "all"],
                   help="Platform (default: android)")
    p.add_argument("--profile", default=DEFAULT_PROFILE,
                   choices=list(PROFILES.keys()),
                   help=f"Build profile (default: {DEFAULT_PROFILE})")
    p.add_argument("--dest",    default=None, metavar="PATH",
                   help="Download destination (default: ~/Downloads/)")
    p.add_argument("--dry-run", "-n", action="store_true",
                   help="Print steps, don't execute")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print("\n  Computer Black — EAS Build")

    if args.profiles:
        print("\n  Build profiles:")
        for name, cfg in PROFILES.items():
            print(f"    {name:15s}  {cfg.get('description', '')}")
        return

    if args.status:
        plat = args.platform if args.platform != "all" else "android"
        get_build_status(args.project, platform=plat)
        return

    if args.download:
        download_artifact(args.download, dest=args.dest)
        return

    # --build
    platforms = ["android", "ios"] if args.platform == "all" else [args.platform]
    for plat in platforms:
        trigger_build(
            project_key=args.project,
            platform=plat,
            profile=args.profile,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
