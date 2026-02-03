#!/usr/bin/env python3
"""List PagerDuty incidents with optional filters.

Usage:
    python list_incidents.py [--status STATUS] [--days N] [--limit N]

Examples:
    python list_incidents.py
    python list_incidents.py --status triggered
    python list_incidents.py --status acknowledged --limit 10
    python list_incidents.py --days 7
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

from pagerduty_client import list_incidents, format_incident


def main():
    parser = argparse.ArgumentParser(
        description="List PagerDuty incidents"
    )
    parser.add_argument(
        "--status",
        choices=["triggered", "acknowledged", "resolved"],
        help="Filter by status",
    )
    parser.add_argument(
        "--service",
        help="Filter by service ID",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum incidents to return (default: 25)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        since = (datetime.utcnow() - timedelta(days=args.days)).isoformat() + "Z"
        until = datetime.utcnow().isoformat() + "Z"

        service_ids = [args.service] if args.service else None

        incidents = list_incidents(
            status=args.status,
            service_ids=service_ids,
            since=since,
            until=until,
            limit=args.limit,
        )

        if args.json:
            output = {
                "filters": {
                    "status": args.status,
                    "service_id": args.service,
                    "days": args.days,
                },
                "count": len(incidents),
                "incidents": [
                    {
                        "id": inc.get("id"),
                        "title": inc.get("title"),
                        "status": inc.get("status"),
                        "urgency": inc.get("urgency"),
                        "created_at": inc.get("created_at"),
                        "service": inc.get("service", {}).get("summary"),
                        "html_url": inc.get("html_url"),
                    }
                    for inc in incidents
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print("PAGERDUTY INCIDENTS")
            print("=" * 60)
            if args.status:
                print(f"Status: {args.status}")
            print(f"Time range: last {args.days} days")
            print(f"Found: {len(incidents)} incidents")
            print()

            if not incidents:
                print("No incidents found matching criteria.")
            else:
                # Group by status
                by_status = {}
                for inc in incidents:
                    status = inc.get("status", "unknown")
                    if status not in by_status:
                        by_status[status] = []
                    by_status[status].append(inc)

                for status in ["triggered", "acknowledged", "resolved"]:
                    if status in by_status:
                        print(f"\n{status.upper()} ({len(by_status[status])})")
                        print("-" * 40)
                        for inc in by_status[status]:
                            print(format_incident(inc))
                            print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
