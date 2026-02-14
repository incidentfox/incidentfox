#!/usr/bin/env python3
"""Execute MetricsQL queries against VictoriaMetrics.

Context-efficient: defaults to instant queries (single value per series),
caps output to --limit series, and shows only latest values for range queries.

Usage:
    python query_metrics.py --query METRICSQL [--type instant|range] [--limit N]

Examples:
    python query_metrics.py --query 'up{job="api"}'
    python query_metrics.py --query 'topk(5, rate(http_requests_total[5m]))' --type range
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from victoriametrics_client import (
    format_metric_result,
    query_instant,
    query_range,
)


def main():
    parser = argparse.ArgumentParser(
        description="Execute MetricsQL queries against VictoriaMetrics"
    )
    parser.add_argument("--query", "-q", required=True, help="MetricsQL/PromQL query")
    parser.add_argument(
        "--type",
        choices=["instant", "range"],
        default="instant",
        help="Query type (default: instant — compact single-value output)",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        default=60,
        help="Time range in minutes for range queries (default: 60)",
    )
    parser.add_argument(
        "--step", default="5m", help="Step for range queries (default: 5m)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max series to display (default: 20)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        if args.type == "instant":
            result = query_instant(args.query)
        else:
            now = datetime.now(timezone.utc)
            start = now - timedelta(minutes=args.time_range)
            result = query_range(args.query, start=start, end=now, step=args.step)

        data = result.get("data", {})
        results = data.get("result", [])

        if args.json:
            # For JSON, include all results but still cap
            output = {
                "query": args.query,
                "type": args.type,
                "result_count": len(results),
                "results": results[: args.limit],
            }
            if len(results) > args.limit:
                output["truncated"] = True
                output["total_series"] = len(results)
            print(json.dumps(output, indent=2))
        else:
            print(f"Query: {args.query}")
            print(f"Type: {args.type}")
            print(f"Results: {len(results)} series")
            print()

            if not results:
                print("No results found.")
            else:
                print(format_metric_result(result, max_series=args.limit))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
