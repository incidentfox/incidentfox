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
        # Redact environment variables in JSON output too
        _sensitive_patterns = [
            "password",
            "secret",
            "token",
            "key",
            "credential",
            "auth",
            "dsn",
            "url",
            "uri",
            "connection",
            "api_key",
            "apikey",
            "access_key",
            "private",
            "jwt",
        ]
        for item in result.get("inspection", []):
            env_list = item.get("Config", {}).get("Env", [])
            for i, e in enumerate(env_list):
                key = e.split("=")[0] if "=" in e else e
                val = e.split("=", 1)[1] if "=" in e else ""
                key_lower = key.lower()
                if any(s in key_lower for s in _sensitive_patterns) or (
                    "://" in val and "@" in val
                ):
                    env_list[i] = f"{key}=***REDACTED***"
        # Remove raw stdout to avoid leaking unredacted data
        result.pop("stdout", None)
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
                _sensitive_patterns = [
                    "password",
                    "secret",
                    "token",
                    "key",
                    "credential",
                    "auth",
                    "dsn",
                    "url",
                    "uri",
                    "connection",
                    "api_key",
                    "apikey",
                    "access_key",
                    "private",
                    "jwt",
                ]
                for e in env[:20]:
                    key = e.split("=")[0] if "=" in e else e
                    val = e.split("=", 1)[1] if "=" in e else ""
                    key_lower = key.lower()
                    # Redact if key matches sensitive pattern or value looks like a URL with credentials
                    if any(s in key_lower for s in _sensitive_patterns) or (
                        "://" in val and "@" in val
                    ):
                        print(f"  {key}=***REDACTED***")
                    else:
                        print(f"  {e}")


if __name__ == "__main__":
    main()
