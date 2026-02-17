#!/usr/bin/env python3
"""List branches in a GitLab project.

Usage:
    python list_branches.py --project "group/project" [--search "feature"]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List GitLab branches")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--search", default="", help="Filter by name")
    parser.add_argument("--max-results", type=int, default=30, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"per_page": args.max_results}
        if args.search:
            params["search"] = args.search

        data = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/repository/branches",
            params=params,
        )
        branches = [
            {
                "name": b["name"],
                "protected": b.get("protected", False),
                "default": b.get("default", False),
                "commit_sha": b.get("commit", {}).get("id"),
                "commit_message": b.get("commit", {}).get("title"),
            }
            for b in data
        ]
        result = {"ok": True, "branches": branches, "count": len(branches)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Branches ({len(branches)} found)")
            for b in branches:
                flags = []
                if b.get("default"):
                    flags.append("default")
                if b.get("protected"):
                    flags.append("protected")
                flag_str = f" ({', '.join(flags)})" if flags else ""
                print(f"  {b['name']}{flag_str}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
