#!/usr/bin/env python3
"""List all Sentry projects in the organization.

Usage:
    python list_projects.py
"""

import argparse
import json
import sys

from sentry_client import get_organization, sentry_request


def main():
    parser = argparse.ArgumentParser(description="List Sentry projects")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        org = get_organization()
        data = sentry_request("GET", f"organizations/{org}/projects/")

        projects = [
            {
                "id": p["id"],
                "slug": p["slug"],
                "name": p["name"],
                "platform": p.get("platform"),
                "status": p.get("status"),
            }
            for p in data
        ]
        result = {
            "ok": True,
            "organization": org,
            "projects": projects,
            "count": len(projects),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Sentry Projects ({org}): {len(projects)}")
            for p in projects:
                print(f"  {p['slug']:30s} ({p.get('platform') or '?'}) - {p['name']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
