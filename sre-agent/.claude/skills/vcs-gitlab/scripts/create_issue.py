#!/usr/bin/env python3
"""Create a new issue in a GitLab project.

Usage:
    python create_issue.py --project "group/project" --title "Title" [--description "Details"]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Create GitLab issue")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--title", required=True, help="Issue title")
    parser.add_argument(
        "--description", default="", help="Issue description (markdown)"
    )
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    parser.add_argument("--assignee-ids", default="", help="Comma-separated user IDs")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        issue_data = {"title": args.title}
        if args.description:
            issue_data["description"] = args.description
        if args.labels:
            issue_data["labels"] = args.labels
        if args.assignee_ids:
            issue_data["assignee_ids"] = [
                int(x.strip()) for x in args.assignee_ids.split(",")
            ]

        issue = gitlab_request(
            "POST",
            f"projects/{encode_project(args.project)}/issues",
            json_body=issue_data,
        )
        result = {
            "ok": True,
            "iid": issue["iid"],
            "title": issue["title"],
            "web_url": issue["web_url"],
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Created: #{result['iid']} - {result['title']}")
            print(f"URL: {result['web_url']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
