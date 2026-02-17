#!/usr/bin/env python3
"""Get details of a specific FireHydrant incident."""

import argparse
import json
import sys

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="Get FireHydrant incident details")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        inc = firehydrant_request("GET", f"/incidents/{args.incident_id}")
        milestones = [
            {
                "type": ms.get("type") or ms.get("slug"),
                "occurred_at": ms.get("occurred_at") or ms.get("created_at"),
                "duration_ms": ms.get("duration"),
            }
            for ms in inc.get("milestones", [])
        ]
        roles = [
            {
                "role": a.get("incident_role", {}).get("name"),
                "user": a.get("user", {}).get("name"),
                "email": a.get("user", {}).get("email"),
            }
            for a in inc.get("role_assignments", [])
        ]

        result = {
            "id": inc.get("id"),
            "name": inc.get("name"),
            "description": inc.get("description"),
            "status": inc.get("current_milestone"),
            "severity": inc.get("severity"),
            "created_at": inc.get("created_at"),
            "customer_impact_summary": inc.get("customer_impact_summary"),
            "milestones": milestones,
            "role_assignments": roles,
            "services": [
                {"id": s.get("id"), "name": s.get("name")}
                for s in inc.get("services", [])
            ],
            "environments": [
                {"id": e.get("id"), "name": e.get("name")}
                for e in inc.get("environments", [])
            ],
            "functionalities": [
                {"id": f.get("id"), "name": f.get("name")}
                for f in inc.get("functionalities", [])
            ],
            "slack_channel_name": inc.get("slack_channel_name"),
            "incident_url": inc.get("incident_url"),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Incident: {result['name']}")
            print(f"Status: {result['status']} | Severity: {result['severity']}")
            if roles:
                print("Roles:")
                for r in roles:
                    print(f"  {r['role']}: {r['user']}")
            if milestones:
                print("Milestones:")
                for m in milestones:
                    print(f"  {m['type']}: {m['occurred_at']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
