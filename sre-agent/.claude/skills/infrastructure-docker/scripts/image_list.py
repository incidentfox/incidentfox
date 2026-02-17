#!/usr/bin/env python3
"""List Docker images.

Usage:
    python image_list.py [--filter "reference=myapp*"]
"""

import argparse
import json
import sys

from docker_runner import parse_pipe_delimited, run_docker


def main():
    parser = argparse.ArgumentParser(description="List Docker images")
    parser.add_argument("--filter", default="", help="Filter pattern")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    docker_args = [
        "images",
        "--format",
        "{{.Repository}}|{{.Tag}}|{{.ID}}|{{.Size}}|{{.CreatedAt}}",
    ]
    if args.filter:
        docker_args.extend(["--filter", args.filter])

    result = run_docker(docker_args)
    if result.get("ok"):
        result["images"] = parse_pipe_delimited(
            result.get("stdout", ""), ["repository", "tag", "id", "size", "created"]
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
        print(f"{'REPOSITORY':40s} {'TAG':15s} {'SIZE':10s} {'ID':15s}")
        for img in result.get("images", []):
            print(
                f"{img['repository']:40s} {img['tag']:15s} {img['size']:10s} {img['id']:15s}"
            )


if __name__ == "__main__":
    main()
