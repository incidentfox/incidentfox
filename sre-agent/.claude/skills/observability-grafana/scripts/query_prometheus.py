#!/usr/bin/env python3
"""Query Prometheus metrics via Grafana.

Usage:
    python query_prometheus.py --query "rate(http_requests_total[5m])"
    python query_prometheus.py --query "up{job='api'}" --time-range 120
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from grafana_client import grafana_request


def main():
    parser = argparse.ArgumentParser(description="Query Prometheus via Grafana")
    parser.add_argument("--query", required=True, help="PromQL query")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--step", default="1m", help="Query step (default: 1m)")
    parser.add_argument(
        "--datasource-id", type=int, default=1, help="Datasource ID (default: 1)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=args.time_range)

        params = {
            "query": args.query,
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "step": args.step,
        }
        data = grafana_request(
            "GET",
            f"api/datasources/proxy/{args.datasource_id}/api/v1/query_range",
            params=params,
        )

        if data.get("status") != "success":
            print(f"Query failed: {data.get('error', 'Unknown')}", file=sys.stderr)
            sys.exit(1)

        results = data.get("data", {}).get("result", [])
        formatted = [
            {"metric": r.get("metric", {}), "values": r.get("values", [])[-100:]}
            for r in results[:20]
        ]
        result = {
            "ok": True,
            "query": args.query,
            "result_count": len(results),
            "results": formatted,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Query: {args.query}")
            print(
                f"Time range: {args.time_range}m | Step: {args.step} | Series: {len(results)}"
            )
            for r in formatted:
                labels = r.get("metric", {})
                label_str = (
                    ", ".join(f"{k}={v}" for k, v in labels.items())
                    if labels
                    else "no labels"
                )
                values = r.get("values", [])
                if values:
                    latest = values[-1]
                    print(f"\n  {{{label_str}}}")
                    print(f"    Latest: {latest[1]} | Points: {len(values)}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
