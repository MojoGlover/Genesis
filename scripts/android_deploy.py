#!/usr/bin/env python3
"""
scripts/android_deploy.py
Thin wrapper — run the android_deploy module from GENESIS root.

Usage (from any directory):
    python /Users/darnieglover/ai/GENESIS/scripts/android_deploy.py [OPTIONS]
    python /Users/darnieglover/ai/GENESIS/scripts/android_deploy.py --help
    python /Users/darnieglover/ai/GENESIS/scripts/android_deploy.py --dry-run
    python /Users/darnieglover/ai/GENESIS/scripts/android_deploy.py --list

This script ensures the GENESIS root is on sys.path so the android_deploy
package can be imported regardless of where you run it from.
"""
import sys
import os

# Ensure GENESIS root is importable
GENESIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GENESIS_ROOT not in sys.path:
    sys.path.insert(0, GENESIS_ROOT)

from android_deploy.__main__ import main

if __name__ == "__main__":
    main()
