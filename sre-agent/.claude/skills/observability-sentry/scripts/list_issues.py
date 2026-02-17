#!/usr/bin/env python3
"""List Sentry issues for a project.

Usage:
    python list_issues.py --project api-backend
    python list_issues.py --project api-backend --query "is:unresolved level:error"
"""

import argparse
import json
import sys

from sentry_client import get_config, get_organization, sentry_request


def main():
    parser = argparse.ArgumentParser(description="List Sentry issues")
    parser.add_argument("--project", default="", help="Project slug")
    parser.add_argument("--query", default="", help="Search query")
    parser.add_argument(
        "--limit", type=int, default=25, help="Max issues (default: 25)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        config = get_config()
        org = get_organization()
        project = args.project or config.get("project")
        if not project:
            print("Error: --project required (or set SENTRY_PROJECT)", file=sys.stderr)
            sys.exit(1)

        params = {"limit": args.limit}
        if args.query:
            params["query"] = args.query

        data = sentry_request("GET", f"projects/{org}/{project}/issues/", params=params)

        issues = [
            {
                "id": i["id"],
                "title": i["title"],
                "short_id": i["shortId"],
                "status": i["status"],
                "level": i["level"],
                "count": i["count"],
                "user_count": i["userCount"],
                "first_seen": i["firstSeen"],
                "last_seen": i["lastSeen"],
                "permalink": i["permalink"],
            }
            for i in data
        ]

        result = {
            "ok": True,
            "project": project,
            "issues": issues,
            "count": len(issues),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Sentry Issues: {project} ({len(issues)} found)")
            for issue in issues:
                print(
                    f"  [{issue['level'].upper()}] #{issue['short_id']} - {issue['title']}"
                )
                print(
                    f"    Events: {issue['count']} | Users: {issue['user_count']} | Status: {issue['status']}"
                )
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
