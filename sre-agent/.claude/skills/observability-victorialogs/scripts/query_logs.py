#!/usr/bin/env python3
"""Execute raw LogsQL queries against VictoriaLogs.

Safety: auto-appends '| limit N' if the query doesn't contain '| limit' or '| stats'.
Handles both log results and stats results.

Usage:
    python query_logs.py --query 'error | stats by (service) count() hits'
    python query_logs.py --query '_stream:{app="api"} AND timeout' --limit 10
    python query_logs.py --query 'status:>=500' --time-range 30 --json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from victorialogs_client import format_log_entry, query_logs


def main():
    parser = argparse.ArgumentParser(
        description="Execute raw LogsQL queries against VictoriaLogs"
    )
    parser.add_argument("--query", "-q", required=True, help="LogsQL query")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max entries to return (default: 50, auto-appended if no | limit in query)",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        default=60,
        help="Time range in minutes (default: 60)",
    )
    parser.add_argument("--start", help="Start time (ISO format)")
    parser.add_argument("--end", help="End time (ISO format)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        now = datetime.now(timezone.utc)

        # Parse start/end if provided
        if args.start:
            start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        else:
            start = now - timedelta(minutes=args.time_range)

        if args.end:
            end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        else:
            end = now

        # Execute query (client auto-appends | limit if needed)
        entries = query_logs(args.query, start=start, end=end, limit=args.limit)

        if args.json:
            result = {
                "query": args.query,
                "count": len(entries),
                "entries": entries,
            }
            print(json.dumps(result, indent=2))
        else:
            print(f"Query: {args.query}")
            print(f"Results: {len(entries)}")
            print()

            if not entries:
                print("No results found.")
            else:
                # Detect if this is a stats result (has aggregation fields, no _msg)
                first = entries[0]
                is_stats = "_msg" not in first and "_time" not in first

                if is_stats:
                    # Stats output: format as table
                    if entries:
                        keys = list(entries[0].keys())
                        # Print header
                        header = "  ".join(f"{k:>15}" for k in keys)
                        print(header)
                        print("-" * len(header))
                        for entry in entries:
                            row = "  ".join(
                                f"{str(entry.get(k, '')):>15}" for k in keys
                            )
                            print(row)
                else:
                    # Log output: format as entries
                    for entry in entries:
                        print(format_log_entry(entry))
                        print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
