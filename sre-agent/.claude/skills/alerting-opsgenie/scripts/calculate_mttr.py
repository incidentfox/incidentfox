#!/usr/bin/env python3
"""Calculate MTTR statistics for Opsgenie alerts.

Usage:
    python calculate_mttr.py [--team-id ID] [--priority P1] [--days 30]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="Calculate MTTR")
    parser.add_argument("--team-id", help="Optional team ID filter")
    parser.add_argument("--priority", help="Optional priority filter (P1-P5)")
    parser.add_argument(
        "--days", type=int, default=30, help="Days to analyze (default: 30)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        query_parts = [
            f"createdAt >= {since} AND createdAt <= {until}",
            "status=closed",
        ]
        if args.team_id:
            query_parts.append(f"responders:{args.team_id}")
        if args.priority:
            query_parts.append(f"priority={args.priority}")

        params = {
            "query": " AND ".join(query_parts),
            "limit": 100,
            "sort": "createdAt",
            "order": "desc",
        }
        mttr_values = []
        offset = 0

        while len(mttr_values) < 500:
            params["offset"] = offset
            data = opsgenie_request("GET", "/v2/alerts", params=params)
            alerts = data.get("data", [])
            if not alerts:
                break

            for alert in alerts:
                close_time = alert.get("report", {}).get("closeTime")
                if close_time:
                    mttr_values.append(close_time / 1000 / 60)

            offset += len(alerts)
            if len(alerts) < params["limit"]:
                break

        if not mttr_values:
            result = {
                "team_id": args.team_id,
                "priority": args.priority,
                "period_days": args.days,
                "alert_count": 0,
                "message": "No closed alerts in this period",
            }
        else:
            mttr_values.sort()
            count = len(mttr_values)
            avg = sum(mttr_values) / count
            result = {
                "team_id": args.team_id,
                "priority": args.priority,
                "period_days": args.days,
                "alert_count": count,
                "mttr_minutes": round(avg, 2),
                "mttr_hours": round(avg / 60, 2),
                "median_minutes": round(mttr_values[count // 2], 2),
                "p95_minutes": (
                    round(mttr_values[int(count * 0.95)], 2)
                    if count > 1
                    else round(mttr_values[0], 2)
                ),
                "fastest_resolution_minutes": round(min(mttr_values), 2),
                "slowest_resolution_minutes": round(max(mttr_values), 2),
            }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"MTTR Statistics (last {args.days} days)")
            if args.team_id:
                print(f"Team: {args.team_id}")
            if args.priority:
                print(f"Priority: {args.priority}")
            print(f"Alerts analyzed: {result.get('alert_count', 0)}")
            if result.get("mttr_minutes"):
                print(
                    f"Average MTTR: {result['mttr_minutes']} min ({result['mttr_hours']} hrs)"
                )
                print(f"Median: {result['median_minutes']} min")
                print(f"P95: {result['p95_minutes']} min")
                print(f"Fastest: {result['fastest_resolution_minutes']} min")
                print(f"Slowest: {result['slowest_resolution_minutes']} min")
            else:
                print(result.get("message", "No data"))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
