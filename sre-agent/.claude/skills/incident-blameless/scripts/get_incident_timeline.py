#!/usr/bin/env python3
"""Get timeline entries for a Blameless incident."""

import argparse
import json
import sys

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="Get incident timeline")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        data = blameless_request(
            "GET",
            f"/incidents/{args.incident_id}/events",
            params={"limit": args.max_results},
        )
        events = data.get("events", data.get("data", []))
        result = [
            {
                "id": e.get("id"),
                "type": e.get("type") or e.get("event_type"),
                "description": e.get("description")
                or e.get("message")
                or e.get("summary"),
                "created_at": e.get("created_at") or e.get("timestamp"),
                "user": (
                    e.get("user", {}).get("name")
                    if isinstance(e.get("user"), dict)
                    else e.get("user")
                ),
            }
            for e in events
        ]

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Timeline for incident {args.incident_id}: {len(result)} events")
            for e in result:
                print(
                    f"  [{e.get('created_at', '?')}] {e.get('type', '?')} - {e.get('description', '')[:100]}"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
