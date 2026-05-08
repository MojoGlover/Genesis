#!/usr/bin/env python3
"""Simple interactive terminal chat with the Math agent."""
import httpx
import sys

URL = "http://localhost:5007/api/chat"

print("\n  Math Agent — type 'quit' to exit\n")

while True:
    try:
        msg = input("  You: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Bye.")
        break

    if not msg:
        continue
    if msg.lower() in ("quit", "exit", "bye"):
        print("  Bye.")
        break

    try:
        r = httpx.post(URL, json={"message": msg}, timeout=30)
        print(f"\n  Math: {r.json()['response']}\n")
    except Exception as e:
        print(f"\n  [error] {e}\n")
