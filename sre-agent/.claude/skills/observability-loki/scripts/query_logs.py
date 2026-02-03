#!/usr/bin/env python3
"""Execute raw LogQL queries against Loki."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from loki_client import format_log_entry, query, query_instant


def format_metric_result(result: list) -> str:
    """Format metric query results."""
    lines = []
    for item in result:
        metric = item.get("metric", {})
        values = item.get("values", [])
        value = item.get("value")  # For instant queries

        # Format metric labels
        if metric:
            label_str = ", ".join(f'{k}="{v}"' for k, v in sorted(metric.items()))
            label_str = f"{{{label_str}}}"
        else:
            label_str = "{}"

        if value:
            # Instant query result
            ts, val = value
            lines.append(f"{label_str} => {val}")
        elif values:
            # Range query result
            lines.append(f"{label_str}:")
            for ts, val in values[-5:]:  # Last 5 values
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                lines.append(f"  {dt.strftime('%H:%M:%S')} => {val}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Execute LogQL queries")
    parser.add_argument("query", help="LogQL query string")
    parser.add_argument(
        "--type",
        "-t",
        choices=["log", "metric"],
        default="log",
        help="Query type: 'log' for streams, 'metric' for aggregations (default: log)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=50,
        help="Max entries for log queries (default: 50)",
    )
    parser.add_argument(
        "--lookback",
        type=float,
        default=1,
        help="Hours to look back (default: 1)",
    )
    parser.add_argument(
        "--start",
        help="Start time (ISO format, e.g., 2024-01-15T10:00:00Z)",
    )
    parser.add_argument(
        "--end",
        help="End time (ISO format, e.g., 2024-01-15T11:00:00Z)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Parse time range
        if args.start:
            start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        else:
            start = datetime.now(timezone.utc) - timedelta(hours=args.lookback)

        if args.end:
            end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc)

        if args.type == "metric":
            # Metric query
            result = query_instant(args.query)
            data = result.get("data", {})
            result_type = data.get("resultType", "vector")
            results = data.get("result", [])

            if args.json:
                print(json.dumps({
                    "query": args.query,
                    "type": result_type,
                    "result": results,
                }, indent=2))
            else:
                print(f"Metric Query: {args.query}")
                print(f"Result Type: {result_type}")
                print()

                if not results:
                    print("No data returned.")
                else:
                    print(format_metric_result(results))

        else:
            # Log query
            result = query(args.query, limit=args.limit, start=start, end=end)
            data = result.get("data", {})
            result_type = data.get("resultType", "streams")
            streams = data.get("result", [])

            if args.json:
                entries = []
                for stream in streams:
                    labels = stream.get("stream", {})
                    for entry in stream.get("values", []):
                        ts_ns, line = entry
                        ts = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)
                        entries.append({
                            "timestamp": ts.isoformat(),
                            "labels": labels,
                            "line": line,
                        })
                entries.sort(key=lambda x: x["timestamp"], reverse=True)
                print(json.dumps({
                    "query": args.query,
                    "count": len(entries),
                    "entries": entries,
                }, indent=2))
            else:
                print(f"Log Query: {args.query}")
                print(f"Time Range: {start.isoformat()} to {end.isoformat()}")
                print()

                # Collect all entries
                all_entries = []
                for stream in streams:
                    labels = stream.get("stream", {})
                    for entry in stream.get("values", []):
                        all_entries.append((labels, entry))

                all_entries.sort(key=lambda x: x[1][0], reverse=True)

                if not all_entries:
                    print("No logs found.")
                    return

                for labels, entry in all_entries[:args.limit]:
                    print(format_log_entry(labels, entry))
                    print()

                print("-" * 60)
                print(f"Returned {len(all_entries)} entries")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
