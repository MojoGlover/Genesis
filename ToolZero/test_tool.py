"""
test_tool.py — Smoke test for any ToolZero-stamped agent.

Usage:
    python3 test_tool.py [--port 5099] [--tool my_tool] [--params '{"key": "val"}']
"""
import argparse
import json
import sys
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",   type=int,  default=5099)
    parser.add_argument("--tool",   type=str,  default=None)
    parser.add_argument("--params", type=str,  default="{}")
    args = parser.parse_args()

    base = f"http://localhost:{args.port}"

    # Health
    print(f"\n[1] GET {base}/health")
    r = httpx.get(f"{base}/health", timeout=5)
    print(f"    Status: {r.status_code}")
    data = r.json()
    print(f"    Tools:  {data.get('tools', [])}")

    # Execute if tool specified
    if args.tool:
        params = json.loads(args.params)
        print(f"\n[2] POST {base}/execute  tool={args.tool}")
        r = httpx.post(f"{base}/execute", json={"tool": args.tool, "params": params}, timeout=10)
        print(f"    Status: {r.status_code}")
        print(f"    Result: {r.json()}")

    print("\n✅ Test complete")


if __name__ == "__main__":
    main()
