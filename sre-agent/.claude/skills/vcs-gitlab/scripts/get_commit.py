#!/usr/bin/env python3
"""Get details of a specific GitLab commit.

Usage:
    python get_commit.py --project "group/project" --sha abc1234
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Get commit details")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--sha", required=True, help="Commit SHA")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        proj = encode_project(args.project)
        commit = gitlab_request("GET", f"projects/{proj}/repository/commits/{args.sha}")
        diff = gitlab_request(
            "GET",
            f"projects/{proj}/repository/commits/{args.sha}/diff",
            params={"per_page": 100},
        )

        files = [
            {
                "old_path": d.get("old_path"),
                "new_path": d.get("new_path"),
                "new_file": d.get("new_file"),
                "deleted_file": d.get("deleted_file"),
                "diff": d.get("diff", "")[:1000],
            }
            for d in (diff or [])[:100]
        ]

        result = {
            "ok": True,
            "id": commit["id"],
            "short_id": commit["short_id"],
            "title": commit["title"],
            "message": commit.get("message"),
            "author_name": commit["author_name"],
            "author_email": commit.get("author_email"),
            "created_at": commit["created_at"],
            "web_url": commit.get("web_url"),
            "parent_ids": commit.get("parent_ids", []),
            "stats": commit.get("stats", {}),
            "files_changed": files,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Commit: {result['short_id']} - {result['title']}")
            print(f"Author: {result['author_name']} | {result['created_at']}")
            stats = result.get("stats", {})
            if stats:
                print(
                    f"Changes: +{stats.get('additions', 0)} -{stats.get('deletions', 0)}"
                )
            if files:
                print(f"\nFiles ({len(files)}):")
                for f in files:
                    print(f"  {f.get('new_path', f.get('old_path', '?'))}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
