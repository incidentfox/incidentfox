#!/usr/bin/env python3
"""List all services traced in Jaeger."""

import argparse
import json
import sys

from jaeger_client import get_services


def main():
    parser = argparse.ArgumentParser(description="List all services in Jaeger")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        services = get_services()

        if args.json:
            print(json.dumps({"services": services, "count": len(services)}, indent=2))
        else:
            print(f"Found {len(services)} services:\n")
            for service in sorted(services):
                print(f"  - {service}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
