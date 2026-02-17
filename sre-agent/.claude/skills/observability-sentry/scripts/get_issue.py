#!/usr/bin/env python3
"""Get details of a specific Sentry issue.

Usage:
    python get_issue.py --issue-id 12345678
"""

import argparse
import json
import sys

from sentry_client import sentry_request


def main():
    parser = argparse.ArgumentParser(description="Get Sentry issue details")
    parser.add_argument("--issue-id", required=True, help="Sentry issue ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        issue = sentry_request("GET", f"issues/{args.issue_id}/")

        result = {
            "ok": True,
            "id": issue["id"],
            "title": issue["title"],
            "short_id": issue["shortId"],
            "status": issue["status"],
            "level": issue["level"],
            "count": issue["count"],
            "user_count": issue["userCount"],
            "first_seen": issue["firstSeen"],
            "last_seen": issue["lastSeen"],
            "permalink": issue["permalink"],
            "metadata": issue.get("metadata", {}),
            "tags": issue.get("tags", []),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Issue: #{result['short_id']} - {result['title']}")
            print(f"Level: {result['level'].upper()} | Status: {result['status']}")
            print(f"Events: {result['count']} | Users: {result['user_count']}")
            print(f"First: {result['first_seen']} | Last: {result['last_seen']}")
            print(f"URL: {result['permalink']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
