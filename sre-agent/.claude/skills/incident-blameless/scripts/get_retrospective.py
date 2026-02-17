#!/usr/bin/env python3
"""Get the retrospective for a Blameless incident.

Returns contributing factors, action items, root cause, and lessons learned.
"""

import argparse
import json
import sys

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="Get incident retrospective")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        data = blameless_request("GET", f"/incidents/{args.incident_id}/retrospective")
        retro = data.get("retrospective", data)

        contributing_factors = [
            {
                "id": f.get("id"),
                "description": f.get("description"),
                "category": f.get("category"),
            }
            for f in retro.get("contributing_factors", [])
        ]
        action_items = [
            {
                "id": a.get("id"),
                "title": a.get("title") or a.get("description"),
                "status": a.get("status"),
                "priority": a.get("priority"),
                "due_date": a.get("due_date"),
                "assignee": (
                    a.get("assignee", {}).get("name")
                    if isinstance(a.get("assignee"), dict)
                    else a.get("assignee")
                ),
            }
            for a in retro.get("action_items", [])
        ]

        result = {
            "incident_id": args.incident_id,
            "summary": retro.get("summary") or retro.get("description"),
            "impact": retro.get("impact"),
            "root_cause": retro.get("root_cause"),
            "contributing_factors": contributing_factors,
            "action_items": action_items,
            "lessons_learned": retro.get("lessons_learned", []),
            "status": retro.get("status"),
            "url": retro.get("url") or retro.get("permalink"),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Retrospective for incident {args.incident_id}")
            if result.get("summary"):
                print(f"Summary: {result['summary']}")
            if result.get("root_cause"):
                print(f"Root Cause: {result['root_cause']}")
            if result.get("impact"):
                print(f"Impact: {result['impact']}")
            if contributing_factors:
                print(f"\nContributing Factors ({len(contributing_factors)}):")
                for f in contributing_factors:
                    print(f"  [{f.get('category', '?')}] {f['description']}")
            if action_items:
                print(f"\nAction Items ({len(action_items)}):")
                for a in action_items:
                    print(
                        f"  [{a.get('status', '?')}] {a['title']} (assignee: {a.get('assignee', '?')})"
                    )
            if result.get("lessons_learned"):
                print("\nLessons Learned:")
                for l in result["lessons_learned"]:
                    print(f"  - {l}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
