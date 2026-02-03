#!/usr/bin/env python3
"""Sample logs from Datadog using intelligent strategies.

Choose the right sampling strategy based on your investigation needs.

Usage:
    python sample_logs.py --strategy STRATEGY [--service SERVICE] [--limit N]

Strategies:
    errors_only   - Only error logs (default for incidents)
    warnings_up   - Warning and error logs
    around_time   - Logs around a specific timestamp
    all           - All log levels

Examples:
    python sample_logs.py --strategy errors_only --service payment
    python sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00Z" --window 5
    python sample_logs.py --strategy all --service checkout --limit 20
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from datadog_client import format_log_entry, search_logs


def main():
    parser = argparse.ArgumentParser(
        description="Sample logs from Datadog using intelligent strategies"
    )
    parser.add_argument(
        "--strategy",
        choices=["errors_only", "warnings_up", "around_time", "all"],
        default="errors_only",
        help="Sampling strategy (default: errors_only)",
    )
    parser.add_argument("--service", help="Service name to filter")
    parser.add_argument("--host", help="Host to filter")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum logs to return (default: 50)"
    )
    parser.add_argument(
        "--timestamp",
        help="ISO timestamp for around_time strategy (e.g., 2026-01-27T05:00:00Z)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=5,
        help="Window in minutes for around_time strategy (default: 5)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build query based on strategy
        query_parts = []

        if args.service:
            query_parts.append(f"service:{args.service}")
        if args.host:
            query_parts.append(f"host:{args.host}")

        # Apply strategy filter
        if args.strategy == "errors_only":
            query_parts.append("status:error")
        elif args.strategy == "warnings_up":
            query_parts.append("(status:error OR status:warn)")

        query = " ".join(query_parts) if query_parts else "*"

        # Handle around_time strategy
        time_range = args.time_range
        if args.strategy == "around_time":
            if not args.timestamp:
                print(
                    "Error: --timestamp required for around_time strategy",
                    file=sys.stderr,
                )
                sys.exit(1)
            # Use smaller window around the timestamp
            time_range = args.window * 2

        # Fetch logs
        logs = search_logs(
            query=query,
            time_range_minutes=time_range,
            limit=args.limit,
        )

        # For around_time, filter to window around timestamp
        if args.strategy == "around_time" and args.timestamp:
            try:
                target = datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))
                window = timedelta(minutes=args.window)
                logs = [
                    log
                    for log in logs
                    if log.get("timestamp")
                    and abs(
                        (
                            datetime.fromisoformat(
                                log["timestamp"].replace("Z", "+00:00")
                            )
                            - target
                        ).total_seconds()
                    )
                    <= window.total_seconds()
                ]
            except ValueError as e:
                print(f"Error parsing timestamp: {e}", file=sys.stderr)
                sys.exit(1)

        result = {
            "strategy": args.strategy,
            "query": query,
            "count": len(logs),
            "limit": args.limit,
            "time_range_minutes": time_range,
            "logs": logs,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print(f"DATADOG LOG SAMPLE ({args.strategy})")
            print("=" * 60)
            print(f"Query: {query}")
            print(f"Found: {len(logs)} logs")
            print()

            if not logs:
                print("No logs found matching criteria.")
            else:
                for log in logs:
                    print(format_log_entry(log))
                    print("-" * 40)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
