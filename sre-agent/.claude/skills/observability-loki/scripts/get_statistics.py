#!/usr/bin/env python3
"""Get log volume and error statistics from Loki."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from loki_client import query, query_instant


def main():
    parser = argparse.ArgumentParser(description="Get log statistics from Loki")
    parser.add_argument(
        "--selector",
        "-s",
        required=True,
        help="Stream selector (e.g., '{app=\"api\"}')",
    )
    parser.add_argument(
        "--lookback",
        type=float,
        default=1,
        help="Hours to look back (default: 1)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=args.lookback)

        # Get total log count
        total_query = f'count_over_time({args.selector}[{args.lookback}h])'
        total_result = query_instant(total_query)

        total_count = 0
        if total_result.get("data", {}).get("result"):
            for item in total_result["data"]["result"]:
                value = item.get("value", [None, "0"])
                total_count += int(float(value[1]))

        # Get error count
        error_selector = f'{args.selector} |~ "(?i)error|exception|fail|fatal"'
        error_query = f'count_over_time({error_selector}[{args.lookback}h])'
        error_result = query_instant(error_query)

        error_count = 0
        if error_result.get("data", {}).get("result"):
            for item in error_result["data"]["result"]:
                value = item.get("value", [None, "0"])
                error_count += int(float(value[1]))

        # Get warning count
        warn_selector = f'{args.selector} |~ "(?i)warn"'
        warn_query = f'count_over_time({warn_selector}[{args.lookback}h])'
        warn_result = query_instant(warn_query)

        warn_count = 0
        if warn_result.get("data", {}).get("result"):
            for item in warn_result["data"]["result"]:
                value = item.get("value", [None, "0"])
                warn_count += int(float(value[1]))

        # Calculate rates
        logs_per_minute = total_count / (args.lookback * 60) if total_count > 0 else 0
        error_rate = (error_count / total_count * 100) if total_count > 0 else 0

        stats = {
            "selector": args.selector,
            "time_range_hours": args.lookback,
            "total_logs": total_count,
            "error_logs": error_count,
            "warning_logs": warn_count,
            "logs_per_minute": round(logs_per_minute, 2),
            "error_rate_percent": round(error_rate, 2),
        }

        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Log Statistics for: {args.selector}")
            print(f"Time window: last {args.lookback}h")
            print()
            print(f"  Total logs:       {total_count:,}")
            print(f"  Error logs:       {error_count:,}")
            print(f"  Warning logs:     {warn_count:,}")
            print()
            print(f"  Logs/minute:      {logs_per_minute:.2f}")
            print(f"  Error rate:       {error_rate:.2f}%")
            print()

            if error_rate > 5:
                print("⚠ High error rate detected!")
            elif error_rate > 1:
                print("Note: Elevated error rate")
            else:
                print("✓ Error rate within normal range")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
