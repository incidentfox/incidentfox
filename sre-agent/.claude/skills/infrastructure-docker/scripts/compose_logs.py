#!/usr/bin/env python3
"""Get Docker Compose service logs.

Usage:
    python compose_logs.py [--services "api,db"] [--tail 100]
"""

import argparse
import json
import sys

from docker_runner import run_docker


def main():
    parser = argparse.ArgumentParser(description="Get Docker Compose logs")
    parser.add_argument(
        "--file", default="docker-compose.yml", help="Compose file path"
    )
    parser.add_argument("--services", default="", help="Comma-separated service names")
    parser.add_argument(
        "--tail", type=int, default=100, help="Lines from end (default: 100)"
    )
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    docker_args = ["compose", "-f", args.file, "logs", "--tail", str(args.tail)]
    if args.services:
        docker_args.extend(args.services.split(","))

    result = run_docker(docker_args, cwd=args.cwd or None)
    if result.get("ok"):
        result["logs"] = result.get("stdout", "")

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
