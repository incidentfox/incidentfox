#!/usr/bin/env python3
"""Get details of a specific merge request.

Usage:
    python get_mr.py --project "group/project" --mr-iid 42
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Get merge request details")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--mr-iid", required=True, type=int, help="MR IID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        mr = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/merge_requests/{args.mr_iid}",
        )

        result = {
            "ok": True,
            "iid": mr["iid"],
            "title": mr["title"],
            "description": mr.get("description"),
            "state": mr["state"],
            "source_branch": mr["source_branch"],
            "target_branch": mr["target_branch"],
            "author": mr.get("author", {}).get("name") if mr.get("author") else None,
            "assignees": [a.get("name") for a in mr.get("assignees", [])],
            "reviewers": [r.get("name") for r in mr.get("reviewers", [])],
            "labels": mr.get("labels", []),
            "web_url": mr["web_url"],
            "merged_at": mr.get("merged_at"),
            "merge_status": mr.get("merge_status"),
            "has_conflicts": mr.get("has_conflicts"),
            "changes_count": mr.get("changes_count"),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"MR !{result['iid']}: {result['title']}")
            print(
                f"State: {result['state']} | {result['source_branch']} -> {result['target_branch']}"
            )
            print(f"Author: {result.get('author', '?')}")
            print(f"URL: {result['web_url']}")
            if result.get("description"):
                print(f"\n{result['description'][:500]}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
