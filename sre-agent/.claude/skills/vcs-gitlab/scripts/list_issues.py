#!/usr/bin/env python3
"""List issues in a GitLab project.

Usage:
    python list_issues.py --project "group/project" [--state opened]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List GitLab issues")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--state", default="opened", help="State: opened, closed, all")
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    parser.add_argument("--max-results", type=int, default=20, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"state": args.state, "per_page": args.max_results}
        if args.labels:
            params["labels"] = args.labels

        data = gitlab_request(
            "GET", f"projects/{encode_project(args.project)}/issues", params=params
        )
        issues = [
            {
                "iid": i["iid"],
                "title": i["title"],
                "state": i["state"],
                "author": i.get("author", {}).get("name") if i.get("author") else None,
                "labels": i.get("labels", []),
                "web_url": i.get("web_url"),
            }
            for i in data
        ]
        result = {"ok": True, "issues": issues, "count": len(issues)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Issues ({len(issues)} {args.state})")
            for issue in issues:
                labels = (
                    f" [{', '.join(issue.get('labels', []))}]"
                    if issue.get("labels")
                    else ""
                )
                print(f"  #{issue['iid']} [{issue['state']}] {issue['title']}{labels}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
