#!/usr/bin/env python3
"""Get timeline updates for an Incident.io incident.

Usage:
    python get_incident_updates.py --incident-id INCIDENT_ID [--max-results 50]
"""

import argparse
import json
import sys

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="Get incident timeline updates")
    parser.add_argument("--incident-id", required=True, help="Incident ID")
    parser.add_argument(
        "--max-results", type=int, default=50, help="Maximum results (default: 50)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = incidentio_request(
            "GET",
            "/incident_updates",
            params={"incident_id": args.incident_id, "page_size": args.max_results},
        )

        updates = []
        for update in data.get("incident_updates", []):
            updates.append(
                {
                    "id": update["id"],
                    "created_at": update.get("created_at"),
                    "message": update.get("message"),
                    "updater": update.get("updater", {}).get("name"),
                    "new_status": update.get("new_incident_status", {}).get("category"),
                    "new_severity": update.get("new_severity", {}).get("name"),
                }
            )

        if args.json:
            print(json.dumps(updates, indent=2))
        else:
            print(
                f"Timeline updates for incident {args.incident_id}: {len(updates)} entries"
            )
            print()
            for u in updates:
                print(f"  [{u.get('created_at', '?')}] {u.get('updater', 'Unknown')}")
                if u.get("new_status"):
                    print(f"    Status changed to: {u['new_status']}")
                if u.get("new_severity"):
                    print(f"    Severity changed to: {u['new_severity']}")
                if u.get("message"):
                    print(f"    {u['message']}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
