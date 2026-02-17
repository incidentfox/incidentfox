#!/usr/bin/env python3
"""Get details of a Linear issue."""

import argparse
import json
import sys

from linear_client import graphql_request


def main():
    parser = argparse.ArgumentParser(description="Get Linear issue")
    parser.add_argument(
        "--issue-id", required=True, help="Issue ID or identifier (e.g. TEAM-123)"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        query = """query GetIssue($id: String!) { issue(id: $id) { id identifier title description state { name } assignee { name } priority createdAt updatedAt url } }"""
        data = graphql_request(query, {"id": args.issue_id})
        issue = data["issue"]
        result = {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "title": issue["title"],
            "description": issue.get("description", ""),
            "state": issue["state"]["name"] if issue.get("state") else None,
            "assignee": issue["assignee"]["name"] if issue.get("assignee") else None,
            "priority": issue.get("priority"),
            "created_at": issue.get("createdAt"),
            "updated_at": issue.get("updatedAt"),
            "url": issue["url"],
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{result['identifier']} - {result['title']}")
            print(
                f"State: {result.get('state', '?')} | Priority: {result.get('priority', '?')} | Assignee: {result.get('assignee', 'Unassigned')}"
            )
            if result.get("description"):
                print(f"Description: {result['description'][:200]}")
            print(f"URL: {result['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
