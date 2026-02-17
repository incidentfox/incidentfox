#!/usr/bin/env python3
"""List Opsgenie alerts with optional filters.

Usage:
    python list_alerts.py [--status open] [--priority P1] [--query QUERY] [--max-results 100]
"""

import argparse
import json
import sys

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="List Opsgenie alerts")
    parser.add_argument("--status", help="Filter by status (open, acked, closed)")
    parser.add_argument("--priority", help="Filter by priority (P1-P5)")
    parser.add_argument("--query", help="Opsgenie search query")
    parser.add_argument("--max-results", type=int, default=100, help="Maximum results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        query_parts = []
        if args.status:
            query_parts.append(f"status={args.status}")
        if args.priority:
            query_parts.append(f"priority={args.priority}")
        if args.query:
            query_parts.append(args.query)

        params = {"limit": min(args.max_results, 100)}
        if query_parts:
            params["query"] = " AND ".join(query_parts)

        all_alerts = []
        offset = 0

        while len(all_alerts) < args.max_results:
            params["offset"] = offset
            data = opsgenie_request("GET", "/v2/alerts", params=params)
            alerts = data.get("data", [])

            if not alerts:
                break

            for alert in alerts:
                all_alerts.append(
                    {
                        "id": alert["id"],
                        "tiny_id": alert.get("tinyId"),
                        "message": alert.get("message"),
                        "status": alert.get("status"),
                        "acknowledged": alert.get("acknowledged", False),
                        "priority": alert.get("priority"),
                        "source": alert.get("source"),
                        "created_at": alert.get("createdAt"),
                        "count": alert.get("count", 1),
                        "tags": alert.get("tags", []),
                        "teams": [t.get("name") for t in alert.get("teams", [])],
                        "owner": alert.get("owner"),
                    }
                )

            offset += len(alerts)
            if len(alerts) < params["limit"]:
                break

        by_status = {}
        by_priority = {}
        for a in all_alerts:
            by_status[a["status"]] = by_status.get(a["status"], 0) + 1
            by_priority[a["priority"]] = by_priority.get(a["priority"], 0) + 1

        result = {
            "ok": True,
            "total_count": len(all_alerts),
            "summary": {"by_status": by_status, "by_priority": by_priority},
            "alerts": all_alerts,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Found: {len(all_alerts)} alerts")
            if by_status:
                print(
                    f"By status: {', '.join(f'{k}: {v}' for k, v in by_status.items())}"
                )
            if by_priority:
                print(
                    f"By priority: {', '.join(f'{k}: {v}' for k, v in by_priority.items())}"
                )
            print()
            for a in all_alerts:
                ack = " [ACK]" if a["acknowledged"] else ""
                print(f"  [{a['priority']}] {a['message']}{ack}")
                print(f"    Status: {a['status']} | Source: {a.get('source', '?')}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
