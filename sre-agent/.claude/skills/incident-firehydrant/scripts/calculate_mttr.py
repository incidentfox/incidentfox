#!/usr/bin/env python3
"""Calculate MTTR for FireHydrant incidents."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="Calculate MTTR")
    parser.add_argument("--severity", help="Severity filter")
    parser.add_argument("--service-id", help="Service ID filter")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()
        params = {"per_page": 100, "start_date": since, "end_date": until}
        if args.severity:
            params["severity"] = args.severity

        mttr_values, page = [], 1
        while True:
            params["page"] = page
            data = firehydrant_request("GET", "/incidents", params=params)
            incidents = data.get("data", [])
            if not incidents:
                break
            for inc in incidents:
                resolved_at = None
                for ms in inc.get("milestones", []):
                    if (ms.get("type") or ms.get("slug")) == "resolved":
                        resolved_at = ms.get("occurred_at") or ms.get("created_at")
                start = inc.get("started_at") or inc.get("created_at", "")
                if start and resolved_at:
                    try:
                        mttr = (
                            datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
                            - datetime.fromisoformat(start.replace("Z", "+00:00"))
                        ).total_seconds() / 60
                        mttr_values.append(mttr)
                    except (ValueError, KeyError, TypeError):
                        pass
            page += 1
            if len(incidents) < params["per_page"]:
                break

        mttr_values.sort()
        if not mttr_values:
            result = {
                "severity": args.severity,
                "service_id": args.service_id,
                "period_days": args.days,
                "incident_count": 0,
                "message": "No resolved incidents",
            }
        else:
            count = len(mttr_values)
            avg = sum(mttr_values) / count
            result = {
                "severity": args.severity,
                "service_id": args.service_id,
                "period_days": args.days,
                "incident_count": count,
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
            print(
                f"MTTR (last {args.days} days): {result.get('incident_count', 0)} incidents"
            )
            if result.get("mttr_minutes"):
                print(
                    f"Avg: {result['mttr_minutes']} min | Median: {result['median_minutes']} min | P95: {result['p95_minutes']} min"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
