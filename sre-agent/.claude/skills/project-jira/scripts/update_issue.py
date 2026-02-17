#!/usr/bin/env python3
"""Update an existing Jira issue.

Usage:
    python update_issue.py --issue-key PROJ-123 --status "In Progress"
    python update_issue.py --issue-key PROJ-123 --summary "New title" --priority High
"""

import argparse
import json
import sys

from jira_client import jira_request, make_adf_text


def main():
    parser = argparse.ArgumentParser(description="Update a Jira issue")
    parser.add_argument("--issue-key", required=True, help="Issue key (e.g., PROJ-123)")
    parser.add_argument("--summary", default="", help="New summary")
    parser.add_argument("--description", default="", help="New description")
    parser.add_argument("--status", default="", help="New status (triggers transition)")
    parser.add_argument("--priority", default="", help="New priority")
    parser.add_argument("--assignee", default="", help="New assignee account ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        fields = {}
        if args.summary:
            fields["summary"] = args.summary
        if args.description:
            fields["description"] = make_adf_text(args.description)
        if args.priority:
            fields["priority"] = {"name": args.priority}

        if fields:
            jira_request(
                "PUT", f"/issue/{args.issue_key}", json_body={"fields": fields}
            )

        if args.assignee:
            jira_request(
                "PUT",
                f"/issue/{args.issue_key}/assignee",
                json_body={"accountId": args.assignee},
            )

        if args.status:
            transitions = jira_request("GET", f"/issue/{args.issue_key}/transitions")
            for transition in transitions.get("transitions", []):
                if transition["name"].lower() == args.status.lower():
                    jira_request(
                        "POST",
                        f"/issue/{args.issue_key}/transitions",
                        json_body={"transition": {"id": transition["id"]}},
                    )
                    break
            else:
                available = [t["name"] for t in transitions.get("transitions", [])]
                print(
                    f"Warning: Status '{args.status}' not found. Available: {', '.join(available)}",
                    file=sys.stderr,
                )

        result = {"ok": True, "key": args.issue_key, "updated": True}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Updated: {args.issue_key}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
