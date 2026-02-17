#!/usr/bin/env python3
"""Get timeline events for a FireHydrant incident."""

import argparse
import json
import sys

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="Get incident timeline")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        data = firehydrant_request(
            "GET",
            f"/incidents/{args.incident_id}/events",
            params={"per_page": args.max_results},
        )
        events = [
            {
                "id": e.get("id"),
                "type": e.get("type"),
                "occurred_at": e.get("occurred_at") or e.get("created_at"),
                "description": e.get("description")
                or e.get("body")
                or e.get("summary"),
                "author": (
                    e.get("author", {}).get("name")
                    if isinstance(e.get("author"), dict)
                    else e.get("author")
                ),
                "visibility": e.get("visibility"),
            }
            for e in data.get("data", [])
        ]

        if args.json:
            print(json.dumps(events, indent=2))
        else:
            print(f"Timeline: {len(events)} events")
            for e in events:
                print(
                    f"  [{e.get('occurred_at', '?')}] {e.get('type', '?')} - {(e.get('description', '') or '')[:100]}"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
