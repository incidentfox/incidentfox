#!/usr/bin/env python3
"""Get comprehensive log statistics from VictoriaLogs — THE MANDATORY FIRST STEP.

Uses server-side LogsQL aggregation to return a compact summary. Never dumps raw logs.

Output includes:
- Total count, error count, error rate percentage
- Logs per minute
- Top 10 streams by volume
- Top error patterns (normalized and deduplicated)
- Actionable recommendation

Usage:
    python get_statistics.py
    python get_statistics.py --query '_stream:{app="api"}'
    python get_statistics.py --time-range 120 --json
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from victorialogs_client import normalize_message, query_logs


def main():
    parser = argparse.ArgumentParser(
        description="Get log statistics from VictoriaLogs (ALWAYS call first)"
    )
    parser.add_argument(
        "--query",
        "-q",
        default="*",
        help="LogsQL filter (default: * = all logs)",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        default=60,
        help="Time range in minutes (default: 60)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=args.time_range)
        base_query = args.query

        # 1. Total count (server-side aggregation)
        total_entries = query_logs(
            f"{base_query} | stats count() total",
            start=start,
            end=now,
            limit=1,
        )
        total_count = 0
        if total_entries:
            total_count = int(total_entries[0].get("total", 0))

        # 2. Error count (server-side aggregation)
        error_entries = query_logs(
            f"{base_query} AND (error OR exception OR fail OR fatal) | stats count() errors",
            start=start,
            end=now,
            limit=1,
        )
        error_count = 0
        if error_entries:
            error_count = int(error_entries[0].get("errors", 0))

        # 3. Warning count
        warn_entries = query_logs(
            f"{base_query} AND (warn OR warning) | stats count() warnings",
            start=start,
            end=now,
            limit=1,
        )
        warn_count = 0
        if warn_entries:
            warn_count = int(warn_entries[0].get("warnings", 0))

        # 4. Top streams (server-side aggregation, top 10)
        stream_entries = query_logs(
            f"{base_query} | stats by (_stream) count() hits | sort by (hits) desc | limit 10",
            start=start,
            end=now,
            limit=10,
        )
        top_streams = []
        for entry in stream_entries:
            stream = entry.get("_stream", "unknown")
            hits = int(entry.get("hits", 0))
            top_streams.append({"stream": stream, "count": hits})

        # 5. Top error patterns (server-side aggregation + client-side normalization)
        error_msg_entries = query_logs(
            f"{base_query} AND (error OR exception) | stats by (_msg) count() hits | sort by (hits) desc | limit 30",
            start=start,
            end=now,
            limit=30,
        )
        # Normalize and re-aggregate client-side
        pattern_counter = Counter()
        for entry in error_msg_entries:
            msg = entry.get("_msg", "")
            hits = int(entry.get("hits", 1))
            normalized = normalize_message(msg)
            pattern_counter[normalized] += hits

        top_error_patterns = [
            {"pattern": pattern, "count": count}
            for pattern, count in pattern_counter.most_common(10)
        ]

        # Calculate rates
        error_rate = round(error_count / total_count * 100, 2) if total_count > 0 else 0
        warn_rate = round(warn_count / total_count * 100, 2) if total_count > 0 else 0
        logs_per_minute = (
            round(total_count / args.time_range, 2) if total_count > 0 else 0
        )

        # Build recommendation
        if total_count == 0:
            recommendation = "No logs found in the specified time range."
        elif error_rate > 10:
            recommendation = f"HIGH error rate ({error_rate}%). Investigate top error patterns immediately."
        elif error_rate > 5:
            recommendation = (
                f"Elevated error rate ({error_rate}%). Review error patterns."
            )
        elif total_count > 100000:
            recommendation = f"High volume ({total_count:,} logs). Use stream filters to narrow down."
        else:
            recommendation = (
                f"Normal volume ({total_count:,} logs). Error rate: {error_rate}%"
            )

        result = {
            "query": base_query,
            "time_range_minutes": args.time_range,
            "total_count": total_count,
            "error_count": error_count,
            "warning_count": warn_count,
            "error_rate_percent": error_rate,
            "warning_rate_percent": warn_rate,
            "logs_per_minute": logs_per_minute,
            "top_streams": top_streams,
            "top_error_patterns": top_error_patterns,
            "recommendation": recommendation,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 55)
            print("VICTORIALOGS STATISTICS")
            print("=" * 55)
            print(f"Query: {base_query}")
            print(f"Time Range: {args.time_range} minutes")
            print()
            print(f"Total Logs:    {total_count:,}")
            print(f"Errors:        {error_count:,} ({error_rate}%)")
            print(f"Warnings:      {warn_count:,} ({warn_rate}%)")
            print(f"Logs/minute:   {logs_per_minute:.2f}")
            print()

            if top_streams:
                print("Top Streams:")
                for s in top_streams[:10]:
                    print(f"  {s['stream']}: {s['count']:,}")
                print()

            if top_error_patterns:
                print("Top Error Patterns:")
                for p in top_error_patterns[:5]:
                    print(f"  [{p['count']}x] {p['pattern'][:80]}")
                print()

            print(f"Recommendation: {recommendation}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
