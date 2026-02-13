#!/usr/bin/env python3
"""Get metric statistics from VictoriaMetrics — THE MANDATORY FIRST STEP.

Uses server-side MetricsQL aggregation to return a compact summary of
what metrics exist, their cardinality, and top metric names/jobs.
Never dumps raw series data.

Usage:
    python get_statistics.py --query '{job="api"}'
    python get_statistics.py --query '{namespace="production"}' --time-range 120

Examples:
    python get_statistics.py --query '{}'
    python get_statistics.py --query '{job=~".*api.*"}' --json
"""

import argparse
import json
import sys

from victoriametrics_client import query_instant


def main():
    parser = argparse.ArgumentParser(
        description="Get metric statistics from VictoriaMetrics (ALWAYS call first)"
    )
    parser.add_argument(
        "--query",
        "-q",
        default="{}",
        help="MetricsQL series selector (default: {} = all)",
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
        selector = args.query

        # 1. Count active series
        count_result = query_instant(f"count({selector})")
        series_count = 0
        count_data = count_result.get("data", {}).get("result", [])
        if count_data:
            series_count = int(float(count_data[0].get("value", [0, "0"])[1]))

        # 2. Top metric names by series count
        top_metrics_result = query_instant(f"topk(10, count by (__name__)({selector}))")
        top_metrics = []
        for item in top_metrics_result.get("data", {}).get("result", []):
            name = item.get("metric", {}).get("__name__", "unknown")
            count = int(float(item.get("value", [0, "0"])[1]))
            top_metrics.append({"name": name, "series_count": count})

        # 3. Top jobs
        top_jobs_result = query_instant(f"topk(5, count by (job)({selector}))")
        top_jobs = []
        for item in top_jobs_result.get("data", {}).get("result", []):
            job = item.get("metric", {}).get("job", "unknown")
            count = int(float(item.get("value", [0, "0"])[1]))
            top_jobs.append({"job": job, "series_count": count})

        result = {
            "selector": selector,
            "active_series": series_count,
            "top_metrics": top_metrics,
            "top_jobs": top_jobs,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 50)
            print("VICTORIAMETRICS STATISTICS")
            print("=" * 50)
            print(f"Selector: {selector}")
            print(f"Active series: {series_count:,}")
            print()

            if top_metrics:
                print("Top Metric Names (by series count):")
                for m in top_metrics:
                    print(f"  {m['name']}: {m['series_count']:,}")
                print()

            if top_jobs:
                print("Top Jobs:")
                for j in top_jobs:
                    print(f"  {j['job']}: {j['series_count']:,}")
                print()

            if series_count == 0:
                print("No active series found for this selector.")
            elif series_count > 10000:
                print(
                    f"High cardinality ({series_count:,} series). "
                    "Use specific label filters to narrow down."
                )
            else:
                print(f"Cardinality OK ({series_count:,} series).")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
