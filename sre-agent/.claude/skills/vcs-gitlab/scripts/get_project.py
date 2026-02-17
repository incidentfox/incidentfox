#!/usr/bin/env python3
"""Get GitLab project details.

Usage:
    python get_project.py --project "group/project"
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Get GitLab project details")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        p = gitlab_request("GET", f"projects/{encode_project(args.project)}")
        result = {
            "ok": True,
            "id": p["id"],
            "name": p["name"],
            "path": p["path_with_namespace"],
            "description": p.get("description"),
            "web_url": p["web_url"],
            "default_branch": p.get("default_branch"),
            "visibility": p.get("visibility"),
            "created_at": p.get("created_at"),
            "last_activity_at": p.get("last_activity_at"),
            "forks_count": p.get("forks_count"),
            "star_count": p.get("star_count"),
            "open_issues_count": p.get("open_issues_count"),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Project: {result['path']}")
            print(f"URL: {result['web_url']}")
            print(
                f"Branch: {result.get('default_branch', '?')} | Visibility: {result.get('visibility', '?')}"
            )
            print(
                f"Stars: {result.get('star_count', 0)} | Forks: {result.get('forks_count', 0)} | Issues: {result.get('open_issues_count', 0)}"
            )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
