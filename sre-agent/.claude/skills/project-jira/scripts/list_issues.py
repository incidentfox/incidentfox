#!/usr/bin/env python3
"""List recent issues in a Jira project.

Usage:
    python list_issues.py --project PROJ
    python list_issues.py --project PROJ --max-results 30
"""

import argparse
import json
import sys

from jira_client import get_browse_url, jira_request


def main():
    parser = argparse.ArgumentParser(description="List issues in a Jira project")
    parser.add_argument("--project", required=True, help="Project key (e.g., PROJ)")
    parser.add_argument(
        "--max-results", type=int, default=20, help="Maximum results (default: 20)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        jql = f"project = {args.project} ORDER BY created DESC"
        data = jira_request(
            "GET",
            "/search",
            params={
                "jql": jql,
                "maxResults": args.max_results,
                "fields": "summary,status,issuetype,assignee,created",
            },
        )

        browse_url = get_browse_url()
        issues = []
        for item in data.get("issues", []):
            fields = item.get("fields", {})
            issue = {
                "key": item["key"],
                "summary": fields.get("summary"),
                "status": (
                    fields.get("status", {}).get("name")
                    if fields.get("status")
                    else None
                ),
                "type": (
                    fields.get("issuetype", {}).get("name")
                    if fields.get("issuetype")
                    else None
                ),
                "assignee": (
                    fields.get("assignee", {}).get("displayName")
                    if fields.get("assignee")
                    else None
                ),
                "created": fields.get("created"),
            }
            if browse_url:
                issue["url"] = f"{browse_url}/browse/{item['key']}"
            issues.append(issue)

        result = {
            "ok": True,
            "project": args.project,
            "issues": issues,
            "count": len(issues),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Project: {args.project} ({len(issues)} issues)")
            for issue in issues:
                print(
                    f"  [{issue.get('status', '?')}] {issue['key']} - {issue.get('summary', '')}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
