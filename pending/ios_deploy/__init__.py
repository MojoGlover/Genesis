"""
ios_deploy — iOS build and deploy for Computer Black.

Build IPA via EAS cloud, submit to TestFlight, or sideload via
AltStore/Sideloadly for cable-free iPhone/iPad iteration.

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m ios_deploy --help
    python -m ios_deploy --build            # trigger EAS iOS build
    python -m ios_deploy --testflight       # submit latest IPA to TestFlight
    python -m ios_deploy --sideload         # sideload via AltServer (USB)
    python -m ios_deploy --status           # check current build status
"""
from .builder import build_ios, submit_testflight, sideload
from .config import IOS_CONFIG

__all__ = ["build_ios", "submit_testflight", "sideload", "IOS_CONFIG"]
