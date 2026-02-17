#!/usr/bin/env python3
"""Get log entries for an Opsgenie alert.

Usage:
    python get_alert_logs.py --alert-id ALERT_ID [--max-results 50]
"""

import argparse
import json
import sys

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="Get alert log entries")
    parser.add_argument("--alert-id", required=True, help="Alert ID")
    parser.add_argument("--max-results", type=int, default=50, help="Maximum results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = opsgenie_request(
            "GET",
            f"/v2/alerts/{args.alert_id}/logs",
            params={"limit": args.max_results},
        )
        logs = []
        for log in data.get("data", []):
            logs.append(
                {
                    "log": log.get("log"),
                    "type": log.get("type"),
                    "owner": log.get("owner"),
                    "created_at": log.get("createdAt"),
                }
            )

        if args.json:
            print(json.dumps(logs, indent=2))
        else:
            print(f"Alert logs for {args.alert_id}: {len(logs)} entries")
            print()
            for l in logs:
                print(f"  [{l.get('created_at', '?')}] {l.get('type', '?')}")
                print(f"    {l.get('log', '')}")
                if l.get("owner"):
                    print(f"    By: {l['owner']}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
