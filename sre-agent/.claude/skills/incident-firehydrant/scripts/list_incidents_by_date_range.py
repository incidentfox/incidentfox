#!/usr/bin/env python3
"""List FireHydrant incidents within a date range with MTTR."""

import argparse
import json
import sys
from datetime import datetime

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="List incidents by date range")
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--severity", help="Severity filter")
    parser.add_argument("--max-results", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        params = {"per_page": 100, "start_date": args.since, "end_date": args.until}
        if args.severity:
            params["severity"] = args.severity

        all_incidents, page = [], 1
        while len(all_incidents) < args.max_results:
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
                mttr = None
                start = inc.get("started_at") or inc.get("created_at", "")
                if start and resolved_at:
                    try:
                        mttr = round(
                            (
                                datetime.fromisoformat(
                                    resolved_at.replace("Z", "+00:00")
                                )
                                - datetime.fromisoformat(start.replace("Z", "+00:00"))
                            ).total_seconds()
                            / 60,
                            2,
                        )
                    except:
                        pass
                all_incidents.append(
                    {
                        "id": inc.get("id"),
                        "name": inc.get("name"),
                        "status": inc.get("current_milestone"),
                        "severity": inc.get("severity"),
                        "created_at": inc.get("created_at"),
                        "resolved_at": resolved_at,
                        "mttr_minutes": mttr,
                        "services": [s.get("name") for s in inc.get("services", [])],
                    }
                )
            page += 1
            if len(incidents) < params["per_page"]:
                break

        mttr_values = sorted(
            [i["mttr_minutes"] for i in all_incidents if i["mttr_minutes"]]
        )
        by_severity, by_service = {}, {}
        for i in all_incidents:
            s = i["severity"] or "Unknown"
            by_severity[s] = by_severity.get(s, 0) + 1
            for svc in i.get("services", []):
                if svc:
                    by_service[svc] = by_service.get(svc, 0) + 1

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
            "by_service": dict(
                sorted(by_service.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "incidents": all_incidents,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Period: {args.since} to {args.until}")
            print(f"Total: {len(all_incidents)} | Resolved: {len(mttr_values)}")
            if mttr_values:
                print(f"Avg MTTR: {result['summary']['avg_mttr_minutes']} min")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
