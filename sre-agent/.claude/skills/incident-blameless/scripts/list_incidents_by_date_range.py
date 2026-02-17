#!/usr/bin/env python3
"""List Blameless incidents within a date range with MTTR computation."""

import argparse
import json
import sys
from datetime import datetime

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="List incidents by date range")
    parser.add_argument("--since", required=True, help="Start date (ISO)")
    parser.add_argument("--until", required=True, help="End date (ISO)")
    parser.add_argument("--severity", help="Severity filter (SEV0-SEV4)")
    parser.add_argument("--max-results", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        params = {
            "limit": 100,
            "created_after": args.since,
            "created_before": args.until,
        }
        if args.severity:
            params["severity"] = args.severity

        all_incidents, page = [], 1
        while len(all_incidents) < args.max_results:
            params["page"] = page
            data = blameless_request("GET", "/incidents", params=params)
            incidents = data.get("incidents", data.get("data", []))
            if not incidents:
                break
            for inc in incidents:
                mttr = None
                created, resolved = inc.get("created_at", ""), inc.get("resolved_at")
                if created and resolved:
                    try:
                        c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        r = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                        mttr = round((r - c).total_seconds() / 60, 2)
                    except (ValueError, TypeError):
                        pass
                all_incidents.append(
                    {
                        "id": inc.get("id"),
                        "title": inc.get("title") or inc.get("name"),
                        "status": inc.get("status"),
                        "severity": inc.get("severity"),
                        "created_at": created,
                        "resolved_at": resolved,
                        "mttr_minutes": mttr,
                        "commander": (
                            inc.get("commander", {}).get("name")
                            if isinstance(inc.get("commander"), dict)
                            else inc.get("commander")
                        ),
                    }
                )
            page += 1
            if len(incidents) < params["limit"]:
                break

        mttr_values = sorted(
            [i["mttr_minutes"] for i in all_incidents if i["mttr_minutes"]]
        )
        by_severity = {}
        for i in all_incidents:
            s = i["severity"] or "Unknown"
            by_severity[s] = by_severity.get(s, 0) + 1

        result = {
            "ok": True,
            "period": {"since": args.since, "until": args.until},
            "total_incidents": len(all_incidents),
            "summary": {
                "resolved_count": len(mttr_values),
                "avg_mttr_minutes": (
                    round(sum(mttr_values) / len(mttr_values), 2)
                    if mttr_values
                    else None
                ),
                "median_mttr_minutes": (
                    round(mttr_values[len(mttr_values) // 2], 2)
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
            print(f"Total: {len(all_incidents)} | Resolved: {len(mttr_values)}")
            if mttr_values:
                print(
                    f"Avg MTTR: {result['summary']['avg_mttr_minutes']} min | Median: {result['summary']['median_mttr_minutes']} min"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
