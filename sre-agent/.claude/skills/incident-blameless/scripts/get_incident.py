#!/usr/bin/env python3
"""Get details of a specific Blameless incident."""

import argparse
import json
import sys

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="Get Blameless incident details")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        data = blameless_request("GET", f"/incidents/{args.incident_id}")
        inc = data.get("incident", data)
        roles = [
            {
                "role": r.get("role") or r.get("name"),
                "assignee": (
                    r.get("user", {}).get("name")
                    if isinstance(r.get("user"), dict)
                    else r.get("assignee")
                ),
            }
            for r in inc.get("roles", [])
        ]

        result = {
            "id": inc.get("id"),
            "title": inc.get("title") or inc.get("name"),
            "description": inc.get("description"),
            "status": inc.get("status"),
            "severity": inc.get("severity"),
            "created_at": inc.get("created_at"),
            "resolved_at": inc.get("resolved_at"),
            "commander": (
                inc.get("commander", {}).get("name")
                if isinstance(inc.get("commander"), dict)
                else inc.get("commander")
            ),
            "communication_lead": (
                inc.get("communication_lead", {}).get("name")
                if isinstance(inc.get("communication_lead"), dict)
                else inc.get("communication_lead")
            ),
            "roles": roles,
            "slack_channel": inc.get("slack_channel") or inc.get("slack_channel_name"),
            "postmortem_url": inc.get("postmortem_url") or inc.get("retrospective_url"),
            "url": inc.get("url") or inc.get("permalink"),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Incident: {result['title']}")
            print(f"Status: {result['status']} | Severity: {result['severity']}")
            print(f"Commander: {result.get('commander', 'N/A')}")
            if roles:
                print("Roles:")
                for r in roles:
                    print(f"  {r['role']}: {r['assignee']}")
            if result.get("postmortem_url"):
                print(f"Postmortem: {result['postmortem_url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
