#!/usr/bin/env python3
"""List Linear issues with optional filters."""

import argparse
import json
import sys

from linear_client import graphql_request


def main():
    parser = argparse.ArgumentParser(description="List Linear issues")
    parser.add_argument("--team-id", help="Filter by team ID")
    parser.add_argument("--state", help="Filter by state name")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        query = """query ListIssues($first: Int!) { issues(first: $first) { nodes { id identifier title state { name } assignee { name } priority createdAt url } } }"""
        data = graphql_request(query, {"first": args.max_results})
        issues = []
        for issue in data["issues"]["nodes"]:
            state = issue["state"]["name"] if issue.get("state") else None
            if args.state and state != args.state:
                continue
            issues.append(
                {
                    "id": issue["id"],
                    "identifier": issue["identifier"],
                    "title": issue["title"],
                    "state": state,
                    "assignee": (
                        issue["assignee"]["name"] if issue.get("assignee") else None
                    ),
                    "priority": issue.get("priority"),
                    "created_at": issue.get("createdAt"),
                    "url": issue["url"],
                }
            )

        if args.json:
            print(json.dumps(issues, indent=2))
        else:
            print(f"Issues: {len(issues)}")
            for i in issues:
                print(f"  [{i.get('state', '?')}] {i['identifier']} - {i['title']}")
                print(
                    f"    Priority: {i.get('priority', '?')} | Assignee: {i.get('assignee', 'Unassigned')}"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
