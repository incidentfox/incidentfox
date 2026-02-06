#!/usr/bin/env python3
"""Page a code owner by creating a PagerDuty incident.

Usage:
    python page_code_owner.py --service-id SERVICE_ID --title TITLE --urgency high

Examples:
    python page_code_owner.py --service-id PXXXXXX --title "Enterprise SLA: Acme Corp needs bulk export" --urgency high
    python page_code_owner.py --service-id PXXXXXX --title "Feature request: dark mode" --urgency low --description "Free tier user request"
"""

import argparse
import json
import sys

from pagerduty_client import api_request


def create_incident(
    service_id: str,
    title: str,
    urgency: str = "high",
    description: str = "",
    escalation_policy_id: str | None = None,
) -> dict:
    """Create a PagerDuty incident to page the on-call owner.

    Args:
        service_id: PagerDuty service ID to create incident on
        title: Incident title
        urgency: "high" or "low"
        description: Incident body/details
        escalation_policy_id: Optional escalation policy override

    Returns:
        Created incident object
    """
    payload = {
        "incident": {
            "type": "incident",
            "title": title,
            "urgency": urgency,
            "service": {
                "id": service_id,
                "type": "service_reference",
            },
        }
    }

    if description:
        payload["incident"]["body"] = {
            "type": "incident_body",
            "details": description,
        }

    if escalation_policy_id:
        payload["incident"]["escalation_policy"] = {
            "id": escalation_policy_id,
            "type": "escalation_policy_reference",
        }

    result = api_request("POST", "/incidents", json_data=payload)
    return result.get("incident", {})


def main():
    parser = argparse.ArgumentParser(
        description="Page a code owner by creating a PagerDuty incident"
    )
    parser.add_argument(
        "--service-id",
        required=True,
        help="PagerDuty service ID",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Incident title (e.g. 'Enterprise SLA: Acme Corp needs bulk export')",
    )
    parser.add_argument(
        "--urgency",
        choices=["high", "low"],
        default="high",
        help="Incident urgency (default: high)",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Incident description/details",
    )
    parser.add_argument(
        "--escalation-policy-id",
        default=None,
        help="Optional escalation policy ID override",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        incident = create_incident(
            service_id=args.service_id,
            title=args.title,
            urgency=args.urgency,
            description=args.description,
            escalation_policy_id=args.escalation_policy_id,
        )

        if args.json:
            output = {
                "incident": {
                    "id": incident.get("id"),
                    "title": incident.get("title"),
                    "status": incident.get("status"),
                    "urgency": incident.get("urgency"),
                    "service": incident.get("service", {}).get("summary"),
                    "html_url": incident.get("html_url"),
                    "assignments": [
                        a.get("assignee", {}).get("summary")
                        for a in incident.get("assignments", [])
                    ],
                },
            }
            print(json.dumps(output, indent=2))
        else:
            inc_id = incident.get("id", "unknown")
            title = incident.get("title", "")
            status = incident.get("status", "unknown")
            urgency = incident.get("urgency", "unknown")
            service = incident.get("service", {}).get("summary", "unknown")
            url = incident.get("html_url", "")
            assignments = [
                a.get("assignee", {}).get("summary", "Unknown")
                for a in incident.get("assignments", [])
            ]

            print("=" * 60)
            print("PAGERDUTY INCIDENT CREATED")
            print("=" * 60)
            print(f"  ID:       {inc_id}")
            print(f"  Title:    {title}")
            print(f"  Status:   {status}")
            print(f"  Urgency:  {urgency}")
            print(f"  Service:  {service}")
            if assignments:
                print(f"  Paged:    {', '.join(assignments)}")
            if url:
                print(f"  URL:      {url}")
            print("=" * 60)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
