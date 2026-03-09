"""
ollamactl/__main__.py — Ollama brain manager CLI.

Usage:
    python -m ollamactl --status
    python -m ollamactl --list
    python -m ollamactl --pull llama3.2:3b
    python -m ollamactl --pull blackzero
    python -m ollamactl --delete old-model:latest
    python -m ollamactl --test llama3.2:3b
    python -m ollamactl --set-model llama3.2:3b    # updates MadJanet config
"""
from __future__ import annotations
import argparse
import os
import sys

from .config import OLLAMA_BASE, DEFAULT_MODEL, KNOWN_MODELS
from .client import OllamaClient, check_status, list_models, pull_model


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ollamactl",
        description="Computer Black — Ollama local brain manager",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status",    action="store_true", help="Check if Ollama is reachable")
    g.add_argument("--list",      action="store_true", help="List pulled models")
    g.add_argument("--pull",      metavar="MODEL",     help="Pull a model")
    g.add_argument("--delete",    metavar="MODEL",     help="Delete a local model")
    g.add_argument("--test",      metavar="MODEL",     help="Send a test ping to a model")
    g.add_argument("--set-model", metavar="MODEL",
                   help="Update MadJanet's OLLAMA_MODEL in madjanet_api.ts")

    p.add_argument("--base", default=OLLAMA_BASE,
                   help=f"Ollama base URL (default: {OLLAMA_BASE})")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print(f"\n  Computer Black — Ollama Control  [{args.base}]")

    if args.status:
        ok, msg = check_status(args.base)
        icon = "✓" if ok else "✗"
        print(f"\n  {icon}  {msg}\n")
        sys.exit(0 if ok else 1)

    if args.list:
        models = list_models(args.base)
        if not models:
            print("\n  No models pulled (or Ollama unreachable).")
        else:
            print(f"\n  Pulled models ({len(models)}):")
            for m in models:
                name    = m.get("name", "?")
                size_gb = m.get("size", 0) / 1e9
                marker  = " ◀ active" if name == DEFAULT_MODEL else ""
                print(f"    • {name:30s}  {size_gb:.1f} GB{marker}")
        print(f"\n  Known CB models: {', '.join(KNOWN_MODELS)}\n")
        return

    if args.pull:
        print(f"\n  Pulling: {args.pull}")
        pull_model(args.pull, args.base)
        print(f"  ✓ Done\n")
        return

    if args.delete:
        print(f"\n  Deleting: {args.delete}")
        try:
            OllamaClient(args.base).delete(args.delete)
            print(f"  ✓ Deleted\n")
        except Exception as e:
            print(f"  ✗ Failed: {e}\n")
            sys.exit(1)
        return

    if args.test:
        print(f"\n  Testing {args.test} with ping...")
        try:
            reply = OllamaClient(args.base).chat(args.test, "Say 'pong' and nothing else.")
            print(f"  Response: {reply.strip()}\n")
        except Exception as e:
            print(f"  ✗ Failed: {e}\n")
            sys.exit(1)
        return

    if args.set_model:
        # Update MadJanet's API file
        api_file = os.path.expanduser("~/ai/MadJanet/src/services/madjanet_api.ts")
        if not os.path.isfile(api_file):
            print(f"  ✗ Not found: {api_file}")
            sys.exit(1)
        with open(api_file, "r") as f:
            content = f.read()
        import re
        updated = re.sub(
            r"const OLLAMA_MODEL = '[^']+'",
            f"const OLLAMA_MODEL = '{args.set_model}'",
            content,
        )
        if updated == content:
            print("  ⚠  Pattern not found — no change made.")
        else:
            with open(api_file, "w") as f:
                f.write(updated)
            print(f"  ✓ OLLAMA_MODEL updated to '{args.set_model}' in madjanet_api.ts")
            print(f"    Rebuild APK to apply: python -m android_deploy\n")
        return


if __name__ == "__main__":
    main()
