#!/usr/bin/env python3
"""Get details of a specific Incident.io incident.

Usage:
    python get_incident.py --incident-id INCIDENT_ID
"""

import argparse
import json
import sys

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="Get Incident.io incident details")
    parser.add_argument("--incident-id", required=True, help="Incident ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = incidentio_request("GET", f"/incidents/{args.incident_id}")
        incident = data.get("incident", {})

        roles = []
        for role in incident.get("incident_role_assignments", []):
            roles.append(
                {
                    "role": role.get("role", {}).get("name"),
                    "assignee": role.get("assignee", {}).get("name"),
                }
            )

        custom_fields = [
            {
                "name": cf.get("custom_field", {}).get("name"),
                "value": cf.get("value_text")
                or cf.get("value_option", {}).get("value"),
            }
            for cf in incident.get("custom_field_entries", [])
        ]

        result = {
            "id": incident["id"],
            "name": incident.get("name"),
            "reference": incident.get("reference"),
            "status": incident.get("status", {}).get("category"),
            "severity": incident.get("severity", {}).get("name"),
            "created_at": incident.get("created_at"),
            "updated_at": incident.get("updated_at"),
            "resolved_at": incident.get("resolved_at"),
            "summary": incident.get("summary"),
            "postmortem_document_url": incident.get("postmortem_document_url"),
            "slack_channel_id": incident.get("slack_channel_id"),
            "slack_channel_name": incident.get("slack_channel_name"),
            "roles": roles,
            "custom_fields": custom_fields,
            "url": incident.get("permalink"),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Incident: {result.get('reference', '')} - {result.get('name', '')}")
            print(f"Status: {result.get('status', '?')}")
            print(f"Severity: {result.get('severity', '?')}")
            print(f"Created: {result.get('created_at', '?')}")
            if result.get("resolved_at"):
                print(f"Resolved: {result['resolved_at']}")
            if result.get("summary"):
                print(f"Summary: {result['summary']}")
            if roles:
                print("Roles:")
                for r in roles:
                    print(f"  {r['role']}: {r['assignee']}")
            if custom_fields:
                print("Custom Fields:")
                for cf in custom_fields:
                    print(f"  {cf['name']}: {cf['value']}")
            if result.get("url"):
                print(f"URL: {result['url']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
