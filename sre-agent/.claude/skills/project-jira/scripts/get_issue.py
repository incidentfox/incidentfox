#!/usr/bin/env python3
"""Get details of a specific Jira issue.

Usage:
    python get_issue.py --issue-key PROJ-123
"""

import argparse
import json
import sys

from jira_client import extract_adf_text, get_browse_url, jira_request


def main():
    parser = argparse.ArgumentParser(description="Get Jira issue details")
    parser.add_argument("--issue-key", required=True, help="Issue key (e.g., PROJ-123)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = jira_request("GET", f"/issue/{args.issue_key}")
        fields = data.get("fields", {})
        browse_url = get_browse_url()
        desc = extract_adf_text(fields.get("description"))

        result = {
            "ok": True,
            "key": data["key"],
            "id": data["id"],
            "summary": fields.get("summary"),
            "description": desc,
            "status": (
                fields.get("status", {}).get("name") if fields.get("status") else None
            ),
            "type": (
                fields.get("issuetype", {}).get("name")
                if fields.get("issuetype")
                else None
            ),
            "priority": (
                fields.get("priority", {}).get("name")
                if fields.get("priority")
                else None
            ),
            "assignee": (
                fields.get("assignee", {}).get("displayName")
                if fields.get("assignee")
                else None
            ),
            "reporter": (
                fields.get("reporter", {}).get("displayName")
                if fields.get("reporter")
                else None
            ),
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "labels": fields.get("labels", []),
        }
        if browse_url:
            result["url"] = f"{browse_url}/browse/{data['key']}"

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Issue: {result['key']} - {result.get('summary', '')}")
            if result.get("url"):
                print(f"URL: {result['url']}")
            print(
                f"Status: {result.get('status', '?')} | Type: {result.get('type', '?')} | Priority: {result.get('priority', '?')}"
            )
            print(
                f"Assignee: {result.get('assignee', 'Unassigned')} | Reporter: {result.get('reporter', '?')}"
            )
            if result.get("labels"):
                print(f"Labels: {', '.join(result['labels'])}")
            if desc:
                print(f"\nDescription:\n{desc}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
