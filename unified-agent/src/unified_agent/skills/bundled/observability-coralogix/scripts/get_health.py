#!/usr/bin/env python3
"""Get health summary for a service from Coralogix.

Usage:
    python get_health.py <service> [--app APPLICATION] [--time-range MINUTES]

Examples:
    python get_health.py payment
    python get_health.py checkout --app otel-demo --time-range 30

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
    parser = argparse.ArgumentParser(description="Get service health from Coralogix")
    parser.add_argument("service", help="Service name")
    parser.add_argument(
        "--app", default="otel-demo", help="Application name (default: otel-demo)"
    )
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Get total log count
        total_query = f"source logs | filter $l.applicationname == '{args.app}' | filter $l.subsystemname == '{args.service}' | aggregate count() as total"
        total_results = execute_query(total_query, args.time_range)
        total_count = total_results[0].get("total", 0) if total_results else 0

        # Get error count
        error_query = f"source logs | filter $l.applicationname == '{args.app}' | filter $l.subsystemname == '{args.service}' | filter $m.severity == ERROR || $m.severity == CRITICAL | aggregate count() as errors"
        error_results = execute_query(error_query, args.time_range)
        error_count = error_results[0].get("errors", 0) if error_results else 0

        # Get warning count
        warning_query = f"source logs | filter $l.applicationname == '{args.app}' | filter $l.subsystemname == '{args.service}' | filter $m.severity == WARNING | aggregate count() as warnings"
        warning_results = execute_query(warning_query, args.time_range)
        warning_count = warning_results[0].get("warnings", 0) if warning_results else 0

        # Calculate error rate
        error_rate = (error_count / total_count * 100) if total_count > 0 else 0

        # Determine health status
        if error_count == 0:
            status = "healthy"
            status_icon = "🟢"
        elif error_count < 10 or error_rate < 1:
            status = "degraded"
            status_icon = "🟡"
        elif error_count < 50 or error_rate < 5:
            status = "warning"
            status_icon = "🟠"
        else:
            status = "critical"
            status_icon = "🔴"

        result = {
            "service": args.service,
            "application": args.app,
            "time_range": f"Last {args.time_range} minutes",
            "status": status,
            "total_logs": total_count,
            "error_count": error_count,
            "warning_count": warning_count,
            "error_rate_percent": round(error_rate, 2),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{status_icon} Service Health: {args.service}")
            print(f"Application: {args.app}")
            print(f"Time range: Last {args.time_range} minutes")
            print("-" * 40)
            print(f"Status: {status.upper()}")
            print(f"Total logs: {total_count}")
            print(f"Errors: {error_count} ({error_rate:.2f}%)")
            print(f"Warnings: {warning_count}")

            if status == "critical":
                print()
                print("⚠️  CRITICAL: High error rate detected!")
                print("   Run get_errors.py to see specific errors.")
            elif status == "warning":
                print()
                print("⚠️  WARNING: Elevated error rate.")
                print("   Consider investigating recent errors.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
