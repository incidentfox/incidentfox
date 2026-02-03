#!/usr/bin/env python3
"""Get details of a PagerDuty incident.

Usage:
    python get_incident.py --id INCIDENT_ID

Examples:
    python get_incident.py --id P123ABC
"""

import argparse
import json
import sys

from pagerduty_client import format_incident, get_incident, get_incident_log_entries


def main():
    parser = argparse.ArgumentParser(description="Get details of a PagerDuty incident")
    parser.add_argument(
        "--id",
        required=True,
        help="PagerDuty incident ID",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="Include incident timeline/log entries",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        incident = get_incident(args.id)

        log_entries = []
        if args.timeline:
            log_entries = get_incident_log_entries(args.id)

        if args.json:
            output = {
                "incident": {
                    "id": incident.get("id"),
                    "title": incident.get("title"),
                    "status": incident.get("status"),
                    "urgency": incident.get("urgency"),
                    "created_at": incident.get("created_at"),
                    "service": incident.get("service", {}).get("summary"),
                    "escalation_policy": incident.get("escalation_policy", {}).get(
                        "summary"
                    ),
                    "assignments": [
                        a.get("assignee", {}).get("summary")
                        for a in incident.get("assignments", [])
                    ],
                    "acknowledgements": [
                        {
                            "acknowledger": a.get("acknowledger", {}).get("summary"),
                            "at": a.get("at"),
                        }
                        for a in incident.get("acknowledgements", [])
                    ],
                    "html_url": incident.get("html_url"),
                },
            }
            if log_entries:
                output["timeline"] = [
                    {
                        "type": e.get("type"),
                        "created_at": e.get("created_at"),
                        "summary": e.get("summary"),
                        "agent": e.get("agent", {}).get("summary"),
                    }
                    for e in log_entries
                ]
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print("PAGERDUTY INCIDENT")
            print("=" * 60)
            print(format_incident(incident))
            print()
            print(
                f"Escalation Policy: {incident.get('escalation_policy', {}).get('summary', 'N/A')}"
            )
            print(f"URL: {incident.get('html_url', 'N/A')}")

            assignments = incident.get("assignments", [])
            if assignments:
                print()
                print("ASSIGNMENTS:")
                for a in assignments:
                    print(f"  • {a.get('assignee', {}).get('summary', 'Unknown')}")

            acks = incident.get("acknowledgements", [])
            if acks:
                print()
                print("ACKNOWLEDGEMENTS:")
                for a in acks:
                    print(
                        f"  • {a.get('acknowledger', {}).get('summary', 'Unknown')} at {a.get('at', 'N/A')}"
                    )

            if log_entries:
                print()
                print("TIMELINE:")
                print("-" * 40)
                for entry in log_entries[:20]:
                    entry_type = entry.get("type", "").replace("_", " ")
                    created = entry.get("created_at", "")
                    summary = entry.get("summary", "")[:100]
                    agent = entry.get("agent", {}).get("summary", "")
                    print(f"  [{created}] {entry_type}")
                    if summary:
                        print(f"    {summary}")
                    if agent:
                        print(f"    By: {agent}")
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
