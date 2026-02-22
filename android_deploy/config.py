"""
android_deploy/config.py
Project registry — add any Computer Black React Native / Expo project here.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProjectConfig:
    name: str                        # Human-readable project name
    root: str                        # Absolute path to project root
    entry_file: str = "node_modules/expo/AppEntry.js"
    bundle_output: str = "android/app/src/main/assets/index.android.bundle"
    assets_dest: str = "android/app/src/main/res"
    apk_path: str = "android/app/build/outputs/apk/release/app-release.apk"
    gradle_task: str = "assembleRelease"
    package_name: Optional[str] = None   # Android package, used for --wait launch
    tags: list[str] = field(default_factory=list)


# ── Project Registry ─────────────────────────────────────────────────────────
AI_ROOT = os.path.expanduser("~/ai")

PROJECTS: dict[str, ProjectConfig] = {
    "madjanet": ProjectConfig(
        name="MadJanet",
        root=os.path.join(AI_ROOT, "MadJanet"),
        package_name="com.computerblack.madjanet",
        tags=["voice", "tablet", "android"],
    ),
    # Future projects — uncomment / add as needed:
    # "plugops": ProjectConfig(
    #     name="PlugOps",
    #     root=os.path.join(AI_ROOT, "PlugOps", "mobile"),
    #     package_name="com.computerblack.plugops",
    #     tags=["router", "android"],
    # ),
}

DEFAULT_PROJECT = "madjanet"


def get_project(key: str) -> ProjectConfig:
    key = key.lower().strip()
    if key not in PROJECTS:
        available = ", ".join(PROJECTS.keys())
        raise ValueError(f"Unknown project '{key}'. Available: {available}")
    return PROJECTS[key]


def list_projects() -> None:
    print("\n── Registered Projects ──────────────────────────────────────────")
    for key, cfg in PROJECTS.items():
        tags = ", ".join(cfg.tags) if cfg.tags else "—"
        exists = "✓" if os.path.isdir(cfg.root) else "✗ (not found)"
        print(f"  {key:15s}  {cfg.name:20s}  {exists}  [{tags}]")
    print()
