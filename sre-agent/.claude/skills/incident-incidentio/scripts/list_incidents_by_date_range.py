#!/usr/bin/env python3
"""List Incident.io incidents within a date range with MTTR computation.

Usage:
    python list_incidents_by_date_range.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
"""

import argparse
import json
import sys
from datetime import datetime

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="List incidents by date range")
    parser.add_argument("--since", required=True, help="Start date (ISO format)")
    parser.add_argument("--until", required=True, help="End date (ISO format)")
    parser.add_argument("--status", help="Optional status filter")
    parser.add_argument(
        "--max-results", type=int, default=500, help="Maximum results (default: 500)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {
            "page_size": 100,
            "created_at[gte]": args.since,
            "created_at[lte]": args.until,
        }
        if args.status:
            params["status"] = args.status

        all_incidents = []
        next_cursor = None

        while len(all_incidents) < args.max_results:
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
                mttr_minutes = None
                resolved_at = inc.get("resolved_at")
                if resolved_at:
                    resolved_dt = datetime.fromisoformat(
                        resolved_at.replace("Z", "+00:00")
                    )
                    mttr_minutes = (resolved_dt - created_at).total_seconds() / 60

                all_incidents.append(
                    {
                        "id": inc["id"],
                        "name": inc.get("name"),
                        "reference": inc.get("reference"),
                        "status": inc.get("status", {}).get("category"),
                        "severity": inc.get("severity", {}).get("name"),
                        "created_at": inc["created_at"],
                        "resolved_at": resolved_at,
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                        "incident_lead": inc.get("incident_lead", {}).get("name"),
                        "url": inc.get("permalink"),
                    }
                )

            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        resolved = [i for i in all_incidents if i["mttr_minutes"]]
        mttr_values = [i["mttr_minutes"] for i in resolved]

        by_severity = {}
        for inc in all_incidents:
            sev = inc["severity"] or "Unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1

        result = {
            "ok": True,
            "period": {"since": args.since, "until": args.until},
            "total_incidents": len(all_incidents),
            "summary": {
                "resolved_count": len(resolved),
                "avg_mttr_minutes": (
                    round(sum(mttr_values) / len(mttr_values), 2)
                    if mttr_values
                    else None
                ),
                "median_mttr_minutes": (
                    round(sorted(mttr_values)[len(mttr_values) // 2], 2)
                    if mttr_values
                    else None
                ),
            },
            "by_severity": by_severity,
            "incidents": all_incidents,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Period: {args.since} to {args.until}")
            print(f"Total incidents: {len(all_incidents)}")
            print(f"Resolved: {len(resolved)}")
            if mttr_values:
                print(f"Avg MTTR: {result['summary']['avg_mttr_minutes']} min")
                print(f"Median MTTR: {result['summary']['median_mttr_minutes']} min")
            print(
                f"By severity: {', '.join(f'{k}: {v}' for k, v in by_severity.items())}"
            )
            print()
            for inc in all_incidents[:20]:
                mttr = f" (MTTR: {inc['mttr_minutes']}m)" if inc["mttr_minutes"] else ""
                print(
                    f"  [{inc.get('status', '?')}] {inc.get('reference', '')} - {inc.get('name', '')}{mttr}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
