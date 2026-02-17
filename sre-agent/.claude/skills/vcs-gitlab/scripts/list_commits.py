#!/usr/bin/env python3
"""List commits in a GitLab project.

Usage:
    python list_commits.py --project "group/project" [--ref main]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List GitLab commits")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--ref", default="", help="Branch or tag name")
    parser.add_argument("--path", default="", help="File path filter")
    parser.add_argument("--since", default="", help="Commits after date (ISO 8601)")
    parser.add_argument("--until", default="", help="Commits before date (ISO 8601)")
    parser.add_argument("--max-results", type=int, default=20, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"per_page": args.max_results}
        if args.ref:
            params["ref_name"] = args.ref
        if args.path:
            params["path"] = args.path
        if args.since:
            params["since"] = args.since
        if args.until:
            params["until"] = args.until

        data = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/repository/commits",
            params=params,
        )
        commits = [
            {
                "id": c["id"],
                "short_id": c["short_id"],
                "title": c["title"],
                "author_name": c["author_name"],
                "created_at": c["created_at"],
                "web_url": c.get("web_url"),
            }
            for c in data
        ]
        result = {"ok": True, "commits": commits, "count": len(commits)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Commits ({len(commits)} found)")
            for c in commits:
                print(f"  {c['short_id']} {c['title']}")
                print(f"    Author: {c['author_name']} | {c['created_at']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
