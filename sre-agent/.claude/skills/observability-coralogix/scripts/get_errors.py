#!/usr/bin/env python3
"""Get error logs for a service from Coralogix.

Simplified interface - builds correct DataPrime query automatically.

Usage:
    python get_errors.py <service> [--app APPLICATION] [--time-range MINUTES] [--limit N]

Examples:
    python get_errors.py payment --app otel-demo
    python get_errors.py checkout --time-range 30 --limit 100

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname (e.g., myteam.app.cx498.coralogix.com)
    CORALOGIX_REGION - Region code (e.g., us2, eu1)
"""

import argparse
import json
import sys

from coralogix_client import execute_query, format_log_entry


def main():
    parser = argparse.ArgumentParser(
        description="Get error logs for a service from Coralogix"
    )
    parser.add_argument("service", help="Service name (e.g., payment, checkout)")
    parser.add_argument(
        "--app", default="otel-demo", help="Application name (default: otel-demo)"
    )
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Result limit (default: 50)"
    )
    parser.add_argument(
        "--include-warnings", action="store_true", help="Include WARNING severity"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Build DataPrime query
    query = "source logs"
    query += f" | filter $l.applicationname == '{args.app}'"
    query += f" | filter $l.subsystemname == '{args.service}'"

    if args.include_warnings:
        query += " | filter $m.severity == WARNING || $m.severity == ERROR || $m.severity == CRITICAL"
    else:
        query += " | filter $m.severity == ERROR || $m.severity == CRITICAL"

    query += f" | limit {args.limit}"

    try:
        results = execute_query(
            query=query,
            time_range_minutes=args.time_range,
            limit=args.limit,
        )

        if args.json:
            print(
                json.dumps(
                    {
                        "service": args.service,
                        "application": args.app,
                        "time_range": f"Last {args.time_range} minutes",
                        "error_count": len(results),
                        "errors": results[: args.limit],
                    },
                    indent=2,
                )
            )
        else:
            print(f"Service: {args.service}")
            print(f"Application: {args.app}")
            print(f"Time range: Last {args.time_range} minutes")
            print(f"Errors found: {len(results)}")
            print("-" * 60)

            if not results:
                print("No errors found for this service.")
            else:
                for result in results[: args.limit]:
                    severity = (
                        result.get("severity") or result.get("$m.severity") or "ERROR"
                    )
                    severity_icon = "🔴" if severity == "CRITICAL" else "🟠"
                    print(f"{severity_icon} {format_log_entry(result)}")
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
