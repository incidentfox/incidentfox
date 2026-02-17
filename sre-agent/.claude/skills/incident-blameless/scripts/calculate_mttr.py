#!/usr/bin/env python3
"""Calculate MTTR statistics for Blameless incidents."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="Calculate MTTR")
    parser.add_argument("--severity", help="Severity filter (SEV0-SEV4)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()
        params = {"limit": 100, "created_after": since, "created_before": until}
        if args.severity:
            params["severity"] = args.severity

        mttr_values, page = [], 1
        while True:
            params["page"] = page
            data = blameless_request("GET", "/incidents", params=params)
            incidents = data.get("incidents", data.get("data", []))
            if not incidents:
                break
            for inc in incidents:
                c, r = inc.get("created_at", ""), inc.get("resolved_at")
                if c and r:
                    try:
                        mttr = (
                            datetime.fromisoformat(r.replace("Z", "+00:00"))
                            - datetime.fromisoformat(c.replace("Z", "+00:00"))
                        ).total_seconds() / 60
                        mttr_values.append(mttr)
                    except:
                        pass
            page += 1
            if len(incidents) < params["limit"]:
                break

        mttr_values.sort()
        if not mttr_values:
            result = {
                "severity": args.severity,
                "period_days": args.days,
                "incident_count": 0,
                "message": "No resolved incidents",
            }
        else:
            count = len(mttr_values)
            avg = sum(mttr_values) / count
            result = {
                "severity": args.severity,
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
            print(f"MTTR Statistics (last {args.days} days)")
            if args.severity:
                print(f"Severity: {args.severity}")
            print(f"Incidents: {result.get('incident_count', 0)}")
            if result.get("mttr_minutes"):
                print(
                    f"Avg: {result['mttr_minutes']} min | Median: {result['median_minutes']} min | P95: {result['p95_minutes']} min"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
