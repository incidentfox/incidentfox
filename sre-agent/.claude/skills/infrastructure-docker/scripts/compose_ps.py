#!/usr/bin/env python3
"""List Docker Compose services.

Usage:
    python compose_ps.py [--file docker-compose.yml] [--cwd /path]
"""

import argparse
import json
import sys

from docker_runner import run_docker


def main():
    parser = argparse.ArgumentParser(description="List Docker Compose services")
    parser.add_argument(
        "--file", default="docker-compose.yml", help="Compose file path"
    )
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = run_docker(
        ["compose", "-f", args.file, "ps", "--format", "json"], cwd=args.cwd or None
    )
    if result.get("ok"):
        try:
            result["services"] = json.loads(result.get("stdout", "[]"))
        except json.JSONDecodeError:
            result["services"] = []

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result.get("ok"):
            print(
                f"Error: {result.get('error', result.get('stderr', 'Unknown'))}",
                file=sys.stderr,
            )
            sys.exit(1)
        services = result.get("services", [])
        if isinstance(services, list):
            for svc in services:
                if isinstance(svc, dict):
                    print(
                        f"  {svc.get('Name', '?'):30s} {svc.get('State', '?'):15s} {svc.get('Status', '')}"
                    )
        else:
            print(result.get("stdout", ""))


if __name__ == "__main__":
    main()
