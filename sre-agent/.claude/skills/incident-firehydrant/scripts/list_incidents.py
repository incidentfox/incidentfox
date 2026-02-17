#!/usr/bin/env python3
"""List FireHydrant incidents with optional filters."""

import argparse
import json
import sys

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="List FireHydrant incidents")
    parser.add_argument("--status", help="Filter: open, in_progress, resolved, closed")
    parser.add_argument("--severity", help="Filter by severity")
    parser.add_argument("--environment-id", help="Filter by environment ID")
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        params = {"per_page": min(args.max_results, 100)}
        if args.status:
            params["status"] = args.status
        if args.severity:
            params["severity"] = args.severity
        if args.environment_id:
            params["environment_id"] = args.environment_id

        all_incidents, page = [], 1
        while len(all_incidents) < args.max_results:
            params["page"] = page
            data = firehydrant_request("GET", "/incidents", params=params)
            incidents = data.get("data", [])
            if not incidents:
                break
            for inc in incidents:
                milestones = {}
                for ms in inc.get("milestones", []):
                    ms_type = ms.get("type") or ms.get("slug")
                    if ms_type:
                        milestones[ms_type] = ms.get("occurred_at") or ms.get(
                            "created_at"
                        )
                all_incidents.append(
                    {
                        "id": inc.get("id"),
                        "name": inc.get("name"),
                        "status": inc.get("current_milestone"),
                        "severity": inc.get("severity"),
                        "created_at": inc.get("created_at"),
                        "resolved_at": milestones.get("resolved"),
                        "services": [s.get("name") for s in inc.get("services", [])],
                        "environments": [
                            e.get("name") for e in inc.get("environments", [])
                        ],
                        "incident_url": inc.get("incident_url"),
                    }
                )
            page += 1
            if len(incidents) < params["per_page"]:
                break

        result = {
            "ok": True,
            "total_count": len(all_incidents),
            "incidents": all_incidents,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Found: {len(all_incidents)} incidents")
            for i in all_incidents:
                svcs = f" [{', '.join(i['services'])}]" if i["services"] else ""
                print(f"  [{i.get('status', '?')}] {i.get('name', '')}{svcs}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
