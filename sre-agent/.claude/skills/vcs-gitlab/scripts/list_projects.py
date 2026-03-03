#!/usr/bin/env python3
"""List or search GitLab projects.

Usage:
    python list_projects.py [--search "query"] [--visibility private]
"""

import argparse
import json
import sys

from gitlab_client import gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List GitLab projects")
    parser.add_argument("--search", default="", help="Search query")
    parser.add_argument(
        "--visibility", default="", help="Filter: public, internal, private"
    )
    parser.add_argument(
        "--membership",
        action="store_true",
        default=True,
        help="Only projects the user is a member of (default: true)",
    )
    parser.add_argument(
        "--no-membership",
        action="store_true",
        help="Include all visible projects, not just user's",
    )
    parser.add_argument(
        "--owned", action="store_true", help="Only projects owned by the user"
    )
    parser.add_argument("--max-results", type=int, default=20, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"per_page": args.max_results}
        if args.owned:
            params["owned"] = "true"
        elif not args.no_membership:
            params["membership"] = "true"
        if args.search:
            params["search"] = args.search
        if args.visibility:
            params["visibility"] = args.visibility

        data = gitlab_request("GET", "projects", params=params)
        projects = [
            {
                "id": p["id"],
                "name": p["name"],
                "path": p["path_with_namespace"],
                "web_url": p["web_url"],
                "default_branch": p.get("default_branch"),
                "visibility": p.get("visibility"),
            }
            for p in data
        ]
        result = {"ok": True, "projects": projects, "count": len(projects)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"GitLab Projects ({len(projects)} found)")
            for p in projects:
                print(f"  [{p.get('visibility', '?')}] {p['path']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
