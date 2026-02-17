#!/usr/bin/env python3
"""Calculate MTTR statistics for Incident.io incidents.

Usage:
    python calculate_mttr.py [--severity-id ID] [--days 30]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="Calculate MTTR")
    parser.add_argument("--severity-id", help="Optional severity ID filter")
    parser.add_argument(
        "--days", type=int, default=30, help="Days to analyze (default: 30)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        params = {
            "page_size": 100,
            "created_at[gte]": since,
            "created_at[lte]": until,
            "status": "closed",
        }

        all_incidents = []
        next_cursor = None

        while len(all_incidents) < 500:
            if next_cursor:
                params["after"] = next_cursor

            data = incidentio_request("GET", "/incidents", params=params)
            incidents = data.get("incidents", [])

            if not incidents:
                break

            for inc in incidents:
                created_at = datetime.fromisoformat(
                    inc["created_at"].replace("Z", "+00:00")
                )
                resolved_at = inc.get("resolved_at")
                mttr_minutes = None
                if resolved_at:
                    resolved_dt = datetime.fromisoformat(
                        resolved_at.replace("Z", "+00:00")
                    )
                    mttr_minutes = (resolved_dt - created_at).total_seconds() / 60

                all_incidents.append(
                    {
                        "severity": inc.get("severity", {}).get("name"),
                        "severity_id": inc.get("severity", {}).get("id"),
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                    }
                )

            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        # Filter by severity if specified
        if args.severity_id:
            all_incidents = [
                i for i in all_incidents if i.get("severity_id") == args.severity_id
            ]

        mttr_values = sorted(
            [i["mttr_minutes"] for i in all_incidents if i["mttr_minutes"]]
        )

        if not mttr_values:
            result = {
                "severity_id": args.severity_id,
                "period_days": args.days,
                "incident_count": 0,
                "message": "No resolved incidents in this period",
            }
        else:
            count = len(mttr_values)
            avg_mttr = sum(mttr_values) / count
            result = {
                "severity_id": args.severity_id,
                "period_days": args.days,
                "incident_count": count,
                "mttr_minutes": round(avg_mttr, 2),
                "mttr_hours": round(avg_mttr / 60, 2),
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
            if args.severity_id:
                print(f"Severity filter: {args.severity_id}")
            print(f"Incidents analyzed: {result.get('incident_count', 0)}")
            if result.get("mttr_minutes"):
                print(
                    f"Average MTTR: {result['mttr_minutes']} min ({result['mttr_hours']} hrs)"
                )
                print(f"Median MTTR: {result['median_minutes']} min")
                print(f"P95 MTTR: {result['p95_minutes']} min")
                print(f"Fastest: {result['fastest_resolution_minutes']} min")
                print(f"Slowest: {result['slowest_resolution_minutes']} min")
            else:
                print(result.get("message", "No data"))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
