#!/usr/bin/env python3
"""Execute a command in a running Docker container.

Usage:
    python container_exec.py --container NAME_OR_ID --command "ls -la /app"
"""

import argparse
import json
import sys

from docker_runner import run_docker


def main():
    parser = argparse.ArgumentParser(description="Execute command in container")
    parser.add_argument("--container", required=True, help="Container name or ID")
    parser.add_argument("--command", required=True, help="Command to run")
    parser.add_argument(
        "--workdir", default="", help="Working directory inside container"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    docker_args = ["exec"]
    if args.workdir:
        docker_args.extend(["-w", args.workdir])
    docker_args.append(args.container)
    docker_args.extend(["sh", "-c", args.command])

    result = run_docker(docker_args)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result.get("ok"):
            print(
                f"Error (exit {result.get('exit_code', '?')}): {result.get('stderr', '')}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(result.get("stdout", ""))


if __name__ == "__main__":
    main()
