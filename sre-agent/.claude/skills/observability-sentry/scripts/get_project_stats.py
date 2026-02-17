#!/usr/bin/env python3
"""Get statistics for a Sentry project.

Usage:
    python get_project_stats.py --project api-backend
    python get_project_stats.py --project api-backend --stat received --resolution 1d
"""

import argparse
import json
import sys

from sentry_client import get_organization, sentry_request


def main():
    parser = argparse.ArgumentParser(description="Get Sentry project statistics")
    parser.add_argument("--project", required=True, help="Project slug")
    parser.add_argument(
        "--stat",
        default="received",
        choices=["received", "rejected", "blacklisted"],
        help="Stat type",
    )
    parser.add_argument(
        "--resolution", default="1h", help="Resolution (1h, 1d, 1w, 1m)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        org = get_organization()
        data = sentry_request(
            "GET",
            f"projects/{org}/{args.project}/stats/",
            params={"stat": args.stat, "resolution": args.resolution},
        )

        result = {
            "ok": True,
            "project": args.project,
            "stat": args.stat,
            "resolution": args.resolution,
            "data": data,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Project Stats: {args.project} ({args.stat}, {args.resolution})")
            if isinstance(data, list):
                total = sum(point[1] for point in data if len(point) > 1)
                print(f"Total events: {total} | Data points: {len(data)}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
