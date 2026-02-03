#!/usr/bin/env python3
"""List operations for a service in Jaeger."""

import argparse
import json
import sys

from jaeger_client import get_operations


def main():
    parser = argparse.ArgumentParser(description="List operations for a service")
    parser.add_argument("service", help="Service name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        operations = get_operations(args.service)

        if args.json:
            print(
                json.dumps(
                    {
                        "service": args.service,
                        "operations": operations,
                        "count": len(operations),
                    },
                    indent=2,
                )
            )
        else:
            print(f"Operations for '{args.service}' ({len(operations)} found):\n")
            for op in sorted(operations):
                print(f"  - {op}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
