#!/usr/bin/env python3
"""
Accountant — CLI entry point.

Usage:
    python main.py status
    python main.py report daily
    python main.py report monthly
    python main.py report tax [--year 2025]
    python main.py track <vendor> <service> <amount> <category>
    python main.py optimize
    python main.py forecast
    python main.py export-tax [--year 2025]
    python main.py alerts
    python main.py chat
"""
import argparse
import sys
from pathlib import Path

# Allow running directly or via module
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from . import accountant


def main():
    parser = argparse.ArgumentParser(
        prog="accountant",
        description="Accountant — System Economic Intelligence",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status",   help="Full financial status")
    sub.add_parser("optimize", help="Cost optimization recommendations")
    sub.add_parser("forecast", help="Cost projections")
    sub.add_parser("alerts",   help="Run budget and anomaly checks")

    rep = sub.add_parser("report", help="Generate a report")
    rep.add_argument("period", choices=["daily","weekly","monthly","tax","agents","forecast"])
    rep.add_argument("--year", type=int, default=None)

    trk = sub.add_parser("track", help="Manually record a cost")
    trk.add_argument("vendor")
    trk.add_argument("service")
    trk.add_argument("amount", type=float)
    trk.add_argument("category")
    trk.add_argument("--agent",   default="manual")
    trk.add_argument("--notes",   default="")

    exp = sub.add_parser("export-tax", help="Export tax CSV")
    exp.add_argument("--year", type=int, default=None)
    exp.add_argument("--out",  default=None)

    sub.add_parser("chat", help="Interactive chat mode")

    args = parser.parse_args()

    if args.command == "status" or args.command is None:
        accountant.status()

    elif args.command == "report":
        print(accountant.report(args.period, year=args.year))

    elif args.command == "optimize":
        accountant.optimize()

    elif args.command == "forecast":
        print(accountant.forecast())

    elif args.command == "alerts":
        alerts = accountant.check_alerts()
        if not alerts:
            print("✅ No active alerts.")
        else:
            for a in alerts:
                print(a)

    elif args.command == "track":
        cost = accountant.track(
            args.vendor, args.service, args.amount, args.category,
            agent=args.agent, notes=args.notes,
        )
        print(f"Recorded: ${cost:.4f} [{args.category}] {args.vendor}/{args.service}")

    elif args.command == "export-tax":
        path = accountant.export_tax_csv(args.year)
        print(f"Exported: {path}")

    elif args.command == "chat":
        _chat_mode()

    else:
        parser.print_help()


def _chat_mode():
    """Interactive chat mode — queries answered by the Ollama accountant model."""
    import httpx
    import json
    import os

    OLLAMA_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434")
    MODEL      = "accountant:latest"

    # Build context from current financial state
    ctx = accountant.report("monthly")
    forecast = accountant.forecast()

    system_prompt = f"""You are the Accountant, the financial intelligence module for Computer Black.

Current financial context:
{ctx}

{forecast}

Answer financial questions precisely. Give numbers when you have them.
Suggest concrete optimizations. Flag risks clearly."""

    print("\n─── Accountant Chat (type 'exit' to quit) ───────────")
    history = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.lower() in ("exit", "quit", "q"):
            break
        if not user_input:
            continue

        history.append({"role": "user", "content": user_input})

        try:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model":    MODEL,
                    "stream":   False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        *history,
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
            reply = resp.json()["message"]["content"]
        except Exception as e:
            reply = f"[Model unavailable: {e}. Run: ollama pull {MODEL}]"

        history.append({"role": "assistant", "content": reply})
        print(f"\nAccountant: {reply}")

    print("\n─────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    main()
