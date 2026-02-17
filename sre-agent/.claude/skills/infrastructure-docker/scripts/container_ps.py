#!/usr/bin/env python3
"""List Docker containers.

Usage:
    python container_ps.py [--all]
"""

import argparse
import json
import sys

from docker_runner import parse_pipe_delimited, run_docker


def main():
    parser = argparse.ArgumentParser(description="List Docker containers")
    parser.add_argument("--all", action="store_true", help="Include stopped containers")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    docker_args = [
        "ps",
        "--format",
        "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}",
    ]
    if args.all:
        docker_args.append("-a")

    result = run_docker(docker_args)
    if result.get("ok"):
        result["containers"] = parse_pipe_delimited(
            result.get("stdout", ""), ["id", "name", "image", "status", "ports"]
        )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result.get("ok"):
            print(
                f"Error: {result.get('error', result.get('stderr', 'Unknown'))}",
                file=sys.stderr,
            )
            sys.exit(1)
        for c in result.get("containers", []):
            print(f"  {c['name']:30s} {c['status']:20s} {c['image']}")


if __name__ == "__main__":
    main()
