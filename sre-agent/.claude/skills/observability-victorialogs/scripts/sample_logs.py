#!/usr/bin/env python3
"""Sample logs from VictoriaLogs using intelligent strategies.

Choose the right sampling strategy based on your investigation needs.
Hard-capped at 50 entries max to protect the context window.

Usage:
    python sample_logs.py --strategy errors_only
    python sample_logs.py --query '_stream:{app="api"}' --strategy errors_only
    python sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00Z" --window 5
    python sample_logs.py --strategy all --limit 20

Strategies:
    errors_only   - Only error/exception/fail logs (default)
    warnings_up   - Warning and error logs
    around_time   - Logs around a specific timestamp
    all           - All log levels
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from victorialogs_client import format_log_entry, query_logs

# Hard maximum to prevent context flooding
MAX_LIMIT = 50


def main():
    parser = argparse.ArgumentParser(
        description="Sample logs from VictoriaLogs using intelligent strategies"
    )
    parser.add_argument(
        "--query",
        "-q",
        default="*",
        help="LogsQL filter (default: * = all)",
    )
    parser.add_argument(
        "--strategy",
        choices=["errors_only", "warnings_up", "around_time", "all"],
        default="errors_only",
        help="Sampling strategy (default: errors_only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help=f"Maximum logs to return (default: 20, max: {MAX_LIMIT})",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        default=60,
        help="Time range in minutes (default: 60)",
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

    # Enforce hard cap
    if args.limit > MAX_LIMIT:
        print(
            f"Warning: --limit clamped from {args.limit} to {MAX_LIMIT}",
            file=sys.stderr,
        )
        args.limit = MAX_LIMIT

    try:
        base_query = args.query
        now = datetime.now(timezone.utc)

        # Build query based on strategy
        if args.strategy == "errors_only":
            logsql = f"{base_query} AND (error OR exception OR fail OR fatal)"
        elif args.strategy == "warnings_up":
            logsql = f"{base_query} AND (error OR warn OR exception)"
        elif args.strategy == "around_time":
            if not args.timestamp:
                print(
                    "Error: --timestamp required for around_time strategy",
                    file=sys.stderr,
                )
                sys.exit(1)
            logsql = base_query
        else:  # all
            logsql = base_query

        # Determine time range
        if args.strategy == "around_time" and args.timestamp:
            try:
                target = datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))
            except ValueError as e:
                print(f"Error parsing timestamp: {e}", file=sys.stderr)
                sys.exit(1)
            window = timedelta(minutes=args.window)
            start = target - window
            end = target + window
        else:
            start = now - timedelta(minutes=args.time_range)
            end = now

        # Fetch logs (limit is enforced by client)
        logs = query_logs(logsql, start=start, end=end, limit=args.limit)

        if args.json:
            result = {
                "strategy": args.strategy,
                "query": logsql,
                "count": len(logs),
                "limit": args.limit,
                "time_range_minutes": args.time_range,
                "logs": logs[: args.limit],
            }
            print(json.dumps(result, indent=2))
        else:
            print("=" * 55)
            print(f"VICTORIALOGS SAMPLE ({args.strategy})")
            print("=" * 55)
            print(f"Query: {logsql}")
            print(f"Found: {len(logs)} logs")
            print()

            if not logs:
                print("No logs found matching criteria.")
            else:
                for entry in logs[: args.limit]:
                    print(format_log_entry(entry))
                    print("-" * 40)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
