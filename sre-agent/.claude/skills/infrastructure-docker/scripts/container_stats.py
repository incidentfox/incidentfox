#!/usr/bin/env python3
"""Get Docker container resource usage statistics.

Usage:
    python container_stats.py [--container NAME_OR_ID]
"""

import argparse
import json
import sys

from docker_runner import parse_pipe_delimited, run_docker


def main():
    parser = argparse.ArgumentParser(description="Container resource usage stats")
    parser.add_argument("--container", default="", help="Specific container (optional)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    docker_args = [
        "stats",
        "--no-stream",
        "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}",
    ]
    if args.container:
        docker_args.append(args.container)

    result = run_docker(docker_args, timeout_s=30.0)
    if result.get("ok"):
        result["stats"] = parse_pipe_delimited(
            result.get("stdout", ""), ["name", "cpu", "memory", "net_io", "block_io"]
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
        print(f"{'NAME':30s} {'CPU':10s} {'MEMORY':25s} {'NET I/O':20s}")
        print("-" * 85)
        for s in result.get("stats", []):
            print(f"{s['name']:30s} {s['cpu']:10s} {s['memory']:25s} {s['net_io']:20s}")


if __name__ == "__main__":
    main()
