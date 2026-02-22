"""
android_deploy — Computer Black Android APK builder and deployer.

A GENESIS module for building standalone release APKs from Expo/React Native
projects and pushing them to Android devices via ADB.

Supported projects: MadJanet (+ future CB mobile apps)

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m android_deploy --help
    python -m android_deploy --dry-run
    python -m android_deploy
"""
from .config import ProjectConfig, get_project, list_projects, PROJECTS
from .builder import build, bundle_js, build_apk, check_prerequisites
from .deployer import deploy, list_devices, install_apk

__all__ = [
    "ProjectConfig",
    "get_project",
    "list_projects",
    "PROJECTS",
    "build",
    "bundle_js",
    "build_apk",
    "check_prerequisites",
    "deploy",
    "list_devices",
    "install_apk",
]
