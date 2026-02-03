#!/usr/bin/env python3
"""Execute PromQL queries against Prometheus.

Usage:
    python query_prometheus.py --query PROMQL [--time-range MINUTES] [--step STEP]

Examples:
    python query_prometheus.py --query "up"
    python query_prometheus.py --query "rate(http_requests_total[5m])" --time-range 60
    python query_prometheus.py --query "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
"""

import argparse
import json
import sys
import time

from grafana_client import (
    query_prometheus,
    query_prometheus_range,
    format_metric_result,
)


def main():
    parser = argparse.ArgumentParser(
        description="Execute PromQL queries against Prometheus"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="PromQL query string",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        help="Time range in minutes (enables range query)",
    )
    parser.add_argument(
        "--step",
        default="1m",
        help="Query step for range queries (default: 1m)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        now = int(time.time())

        if args.time_range:
            # Range query
            start = now - (args.time_range * 60)
            result = query_prometheus_range(
                query=args.query,
                start_seconds=start,
                end_seconds=now,
                step=args.step,
            )
        else:
            # Instant query
            result = query_prometheus(query=args.query)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("PROMETHEUS QUERY RESULT")
            print("=" * 60)
            print(f"Query: {args.query}")
            if args.time_range:
                print(f"Time range: {args.time_range} minutes")
                print(f"Step: {args.step}")
            print()
            print(format_metric_result(result))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
