#!/usr/bin/env python3
"""List releases for a Sentry project.

Usage:
    python list_releases.py --project api-backend
"""

import argparse
import json
import sys

from sentry_client import get_organization, sentry_request


def main():
    parser = argparse.ArgumentParser(description="List Sentry releases")
    parser.add_argument("--project", required=True, help="Project slug")
    parser.add_argument(
        "--limit", type=int, default=10, help="Max releases (default: 10)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        org = get_organization()
        data = sentry_request(
            "GET",
            f"projects/{org}/{args.project}/releases/",
            params={"per_page": args.limit},
        )

        releases = [
            {
                "version": r["version"],
                "short_version": r.get("shortVersion"),
                "date_created": r["dateCreated"],
                "date_released": r.get("dateReleased"),
                "new_groups": r.get("newGroups", 0),
            }
            for r in data
        ]
        result = {
            "ok": True,
            "project": args.project,
            "releases": releases,
            "count": len(releases),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Releases: {args.project} ({len(releases)} found)")
            for r in releases:
                version = r.get("short_version") or r["version"]
                print(
                    f"  {version:30s} Created: {r['date_created']} | New errors: {r.get('new_groups', 0)}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
