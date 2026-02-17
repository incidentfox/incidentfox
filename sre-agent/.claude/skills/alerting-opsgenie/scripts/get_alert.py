#!/usr/bin/env python3
"""Get details of a specific Opsgenie alert.

Usage:
    python get_alert.py --alert-id ALERT_ID
"""

import argparse
import json
import sys

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="Get Opsgenie alert details")
    parser.add_argument("--alert-id", required=True, help="Alert ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = opsgenie_request(
            "GET", f"/v2/alerts/{args.alert_id}", params={"identifierType": "id"}
        )
        alert = data.get("data", {})

        result = {
            "id": alert["id"],
            "tiny_id": alert.get("tinyId"),
            "alias": alert.get("alias"),
            "message": alert.get("message"),
            "description": alert.get("description"),
            "status": alert.get("status"),
            "acknowledged": alert.get("acknowledged", False),
            "priority": alert.get("priority"),
            "source": alert.get("source"),
            "created_at": alert.get("createdAt"),
            "updated_at": alert.get("updatedAt"),
            "acknowledged_at": alert.get("report", {}).get("ackTime"),
            "closed_at": alert.get("report", {}).get("closeTime"),
            "tags": alert.get("tags", []),
            "teams": [t.get("name") for t in alert.get("teams", [])],
            "responders": [
                {"type": r.get("type"), "name": r.get("name") or r.get("id")}
                for r in alert.get("responders", [])
            ],
            "owner": alert.get("owner"),
            "count": alert.get("count", 1),
            "details": alert.get("details", {}),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Alert: [{result['priority']}] {result['message']}")
            print(
                f"Status: {result['status']} | Acknowledged: {result['acknowledged']}"
            )
            print(f"Source: {result.get('source', '?')}")
            print(f"Created: {result.get('created_at', '?')}")
            if result.get("description"):
                print(f"Description: {result['description'][:200]}")
            if result["responders"]:
                print("Responders:")
                for r in result["responders"]:
                    print(f"  {r['type']}: {r['name']}")
            if result["tags"]:
                print(f"Tags: {', '.join(result['tags'])}")
            if result["details"]:
                print("Details:")
                for k, v in result["details"].items():
                    print(f"  {k}: {v}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
