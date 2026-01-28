#!/usr/bin/env python3
"""List all services (subsystems) in Coralogix.

Usage:
    python list_services.py [--time-range MINUTES] [--app APPLICATION]

Examples:
    python list_services.py
    python list_services.py --time-range 120 --app otel-demo

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname (e.g., myteam.app.cx498.coralogix.com)
    CORALOGIX_REGION - Region code (e.g., us2, eu1)
"""

import argparse
import json
import sys

from coralogix_client import execute_query


def main():
    parser = argparse.ArgumentParser(description="List services in Coralogix")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--app", help="Filter by application name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Build DataPrime query
    query = "source logs"
    if args.app:
        query += f" | filter $l.applicationname == '{args.app}'"
    query += " | groupby $l.subsystemname aggregate count() as log_count | orderby log_count desc | limit 50"

    try:
        results = execute_query(
            query=query,
            time_range_minutes=args.time_range,
            limit=50,
        )

        if args.json:
            print(
                json.dumps(
                    {
                        "time_range": f"Last {args.time_range} minutes",
                        "application": args.app,
                        "service_count": len(results),
                        "services": results,
                    },
                    indent=2,
                )
            )
        else:
            print(f"Time range: Last {args.time_range} minutes")
            if args.app:
                print(f"Application: {args.app}")
            print(f"Services found: {len(results)}")
            print("-" * 60)
            print(f"{'SERVICE':<40} {'LOG COUNT':<15}")
            print("-" * 60)

            for result in results:
                service = (
                    result.get("subsystemname")
                    or result.get("$l.subsystemname")
                    or "unknown"
                )
                count = result.get("log_count", 0)
                print(f"{service:<40} {count:<15}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
