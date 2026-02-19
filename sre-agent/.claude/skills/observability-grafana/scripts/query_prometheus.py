#!/usr/bin/env python3
"""Query Prometheus metrics via Grafana.

Usage:
    python query_prometheus.py --query "rate(http_requests_total[5m])"
    python query_prometheus.py --query "up{job='api'}" --time-range 120
    python query_prometheus.py --query "up" --datasource-id 8
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from grafana_client import grafana_request


def find_prometheus_datasource_id():
    """Auto-discover the default Prometheus datasource ID."""
    try:
        datasources = grafana_request("GET", "api/datasources")
        # First try: find the default datasource of type prometheus
        for ds in datasources:
            if ds.get("type") == "prometheus" and ds.get("isDefault"):
                return ds["id"]
        # Second try: find any prometheus datasource
        for ds in datasources:
            if ds.get("type") == "prometheus":
                return ds["id"]
    except Exception:
        pass
    return 1  # fallback


def main():
    parser = argparse.ArgumentParser(description="Query Prometheus via Grafana")
    parser.add_argument("--query", required=True, help="PromQL query")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--step", default="1m", help="Query step (default: 1m)")
    parser.add_argument(
        "--datasource-id", type=int, default=0, help="Datasource ID (0=auto-detect)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        ds_id = args.datasource_id
        if ds_id == 0:
            ds_id = find_prometheus_datasource_id()

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
            f"api/datasources/proxy/{ds_id}/api/v1/query_range",
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
            "datasource_id": ds_id,
            "result_count": len(results),
            "results": formatted,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Query: {args.query}")
            print(
                f"Time range: {args.time_range}m | Step: {args.step} | Datasource: {ds_id} | Series: {len(results)}"
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
