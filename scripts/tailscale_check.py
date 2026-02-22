#!/usr/bin/env python3
"""scripts/tailscale_check.py — wrapper for the tailscale_check module."""
import sys, os
GENESIS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GENESIS_ROOT not in sys.path: sys.path.insert(0, GENESIS_ROOT)
from tailscale_check.__main__ import main
if __name__ == "__main__": main()
