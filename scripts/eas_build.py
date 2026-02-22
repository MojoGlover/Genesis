#!/usr/bin/env python3
"""scripts/eas_build.py — wrapper for the eas_build module."""
import sys, os
GENESIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GENESIS_ROOT not in sys.path: sys.path.insert(0, GENESIS_ROOT)
from eas_build.__main__ import main
if __name__ == "__main__": main()
