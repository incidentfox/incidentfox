#!/usr/bin/env python3
"""Sample logs from Splunk using intelligent strategies.

Choose the right sampling strategy based on your investigation needs.

Usage:
    python sample_logs.py --strategy STRATEGY [--index INDEX] [--sourcetype SOURCETYPE] [--limit N]

Strategies:
    errors_only   - Only error logs (default for incidents)
    warnings_up   - Warning and error logs
    around_time   - Logs around a specific timestamp
    all           - All log levels

Examples:
    python sample_logs.py --strategy errors_only --index main
    python sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00" --window 5
    python sample_logs.py --strategy all --sourcetype access_combined --limit 20
"""

import argparse
import json
import re
import sys

from splunk_client import execute_search, format_log_entry

# Only allow safe characters in SPL field values to prevent query injection.
_SAFE_SPL_FIELD = re.compile(r"^[a-zA-Z0-9_\-.*]+$")

_MAX_TIME_RANGE_MINUTES = 1440
_MAX_LIMIT = 500


def _validate_spl_field(value: str, field_name: str) -> str:
    """Validate a value used in SPL field filters to prevent injection."""
    if not _SAFE_SPL_FIELD.match(value):
        raise ValueError(
            f"Invalid {field_name} value: '{value}'. "
            f"Only alphanumeric, underscore, hyphen, dot, and wildcard (*) are allowed."
        )
    return value


def main():
    parser = argparse.ArgumentParser(
        description="Sample logs from Splunk using intelligent strategies"
    )
    parser.add_argument(
        "--strategy",
        choices=["errors_only", "warnings_up", "around_time", "all"],
        default="errors_only",
        help="Sampling strategy (default: errors_only)",
    )
    parser.add_argument("--index", help="Index name (default: *)")
    parser.add_argument("--sourcetype", help="Sourcetype to filter")
    parser.add_argument("--host", help="Host to filter")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum logs to return (default: 50)"
    )
    parser.add_argument(
        "--timestamp",
        help="Timestamp for around_time strategy (e.g., 2026-01-27T05:00:00)",
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
        # Enforce safety limits
        if args.time_range > _MAX_TIME_RANGE_MINUTES:
            raise ValueError(
                f"Time range {args.time_range}m exceeds maximum ({_MAX_TIME_RANGE_MINUTES}m / 24h)."
            )
        args.limit = min(args.limit, _MAX_LIMIT)

        # Build base search with validated fields
        search_parts = []
        if args.index:
            search_parts.append(f"index={_validate_spl_field(args.index, 'index')}")
        else:
            search_parts.append("index=*")
        if args.sourcetype:
            search_parts.append(f"sourcetype={_validate_spl_field(args.sourcetype, 'sourcetype')}")
        if args.host:
            search_parts.append(f"host={_validate_spl_field(args.host, 'host')}")

        # Apply strategy filter
        if args.strategy == "errors_only":
            search_parts.append(
                "(log_level=ERROR OR log_level=error OR severity=ERROR OR severity=error)"
            )
        elif args.strategy == "warnings_up":
            search_parts.append(
                "(log_level=ERROR OR log_level=error OR log_level=WARN OR log_level=warn OR log_level=WARNING OR severity=ERROR OR severity=WARN)"
            )

        # Handle around_time strategy
        time_range = args.time_range
        if args.strategy == "around_time":
            if not args.timestamp:
                print(
                    "Error: --timestamp required for around_time strategy",
                    file=sys.stderr,
                )
                sys.exit(1)
            # Splunk uses earliest/latest, handled in client
            time_range = args.window * 2

        search_query = " ".join(search_parts) + f" | head {args.limit}"

        # Execute search
        results = execute_search(search_query, time_range, max_results=args.limit)

        # Build output
        logs = []
        for result in results:
            logs.append(
                {
                    "timestamp": result.get("_time"),
                    "level": result.get("log_level") or result.get("severity") or "INFO",
                    "sourcetype": result.get("sourcetype"),
                    "host": result.get("host"),
                    "source": result.get("source"),
                    "message": result.get("_raw"),
                }
            )

        output = {
            "strategy": args.strategy,
            "search": search_query,
            "count": len(logs),
            "limit": args.limit,
            "time_range_minutes": time_range,
            "logs": logs,
        }

        if args.json:
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print(f"SPLUNK LOG SAMPLE ({args.strategy})")
            print("=" * 60)
            print(f"Search: {search_query}")
            print(f"Found: {len(logs)} logs")
            print()

            if not logs:
                print("No logs found matching criteria.")
            else:
                for result in results:
                    print(format_log_entry(result))
                    print("-" * 40)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
