#!/usr/bin/env python3
"""Get Docker container logs.

Usage:
    python container_logs.py --container NAME_OR_ID [--tail 100]
"""

import argparse
import json
import sys

from docker_runner import run_docker


def main():
    parser = argparse.ArgumentParser(description="Get container logs")
    parser.add_argument("--container", required=True, help="Container name or ID")
    parser.add_argument(
        "--tail", type=int, default=100, help="Lines from end (default: 100)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = run_docker(["logs", "--tail", str(args.tail), args.container])
    if result.get("ok"):
        result["logs"] = result.get("stdout", "") + result.get("stderr", "")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result.get("ok"):
            print(
                f"Error: {result.get('error', result.get('stderr', 'Unknown'))}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(result.get("logs", ""))


if __name__ == "__main__":
    main()
