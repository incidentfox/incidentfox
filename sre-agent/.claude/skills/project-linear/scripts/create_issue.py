#!/usr/bin/env python3
"""Create a new Linear issue."""

import argparse
import json
import sys

from linear_client import graphql_request


def main():
    parser = argparse.ArgumentParser(description="Create Linear issue")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--team-id", help="Team ID")
    parser.add_argument(
        "--priority",
        type=int,
        default=0,
        help="0=None, 1=Urgent, 2=High, 3=Medium, 4=Low",
    )
    parser.add_argument("--assignee-id", help="Assignee user ID")
    parser.add_argument("--labels", help="Comma-separated label IDs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        mutation = """mutation CreateIssue($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier title url } } }"""
        input_data = {
            "title": args.title,
            "description": args.description,
            "priority": args.priority,
        }
        if args.team_id:
            input_data["teamId"] = args.team_id
        if args.assignee_id:
            input_data["assigneeId"] = args.assignee_id
        if args.labels:
            input_data["labelIds"] = [l.strip() for l in args.labels.split(",")]

        data = graphql_request(mutation, {"input": input_data})
        issue = data["issueCreate"]["issue"]
        result = {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "title": issue["title"],
            "url": issue["url"],
            "success": True,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Created: {issue['identifier']} - {issue['title']}")
            print(f"URL: {issue['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
