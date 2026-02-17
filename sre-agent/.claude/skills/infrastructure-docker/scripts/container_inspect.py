#!/usr/bin/env python3
"""Inspect a Docker container.

Usage:
    python container_inspect.py --container NAME_OR_ID
"""

import argparse
import json
import sys

from docker_runner import run_docker


def main():
    parser = argparse.ArgumentParser(description="Inspect a Docker container")
    parser.add_argument("--container", required=True, help="Container name or ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = run_docker(["inspect", args.container])
    if result.get("ok"):
        try:
            result["inspection"] = json.loads(result.get("stdout", "[]"))
        except json.JSONDecodeError:
            result["inspection"] = []

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result.get("ok"):
            print(
                f"Error: {result.get('error', result.get('stderr', 'Unknown'))}",
                file=sys.stderr,
            )
            sys.exit(1)
        inspection = result.get("inspection", [{}])
        if inspection:
            info = inspection[0]
            state = info.get("State", {})
            config = info.get("Config", {})
            print(f"Container: {info.get('Name', '?').lstrip('/')}")
            print(f"Image: {config.get('Image', '?')}")
            print(
                f"Status: {state.get('Status', '?')} (Running: {state.get('Running', '?')})"
            )
            print(f"Started: {state.get('StartedAt', '?')}")
            env = config.get("Env", [])
            if env:
                print(f"\nEnvironment ({len(env)} vars):")
                for e in env[:20]:
                    key = e.split("=")[0] if "=" in e else e
                    if any(
                        s in key.lower() for s in ["password", "secret", "token", "key"]
                    ):
                        print(f"  {key}=***REDACTED***")
                    else:
                        print(f"  {e}")


if __name__ == "__main__":
    main()
