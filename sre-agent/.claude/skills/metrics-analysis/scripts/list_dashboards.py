#!/usr/bin/env python3
"""List Grafana dashboards.

Usage:
    python list_dashboards.py [--query SEARCH_TERM]

Examples:
    python list_dashboards.py
    python list_dashboards.py --query "api"
    python list_dashboards.py --query "kubernetes"
"""

import argparse
import json
import sys

from grafana_client import list_dashboards


def main():
    parser = argparse.ArgumentParser(description="List Grafana dashboards")
    parser.add_argument(
        "--query",
        help="Search query to filter dashboards",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        dashboards = list_dashboards(query=args.query)

        if args.json:
            print(json.dumps(dashboards, indent=2))
        else:
            print("=" * 60)
            print("GRAFANA DASHBOARDS")
            if args.query:
                print(f"Search: {args.query}")
            print("=" * 60)
            print(f"Found: {len(dashboards)} dashboards")
            print()

            if not dashboards:
                print("No dashboards found.")
            else:
                for d in dashboards:
                    uid = d.get("uid", "")
                    title = d.get("title", "Untitled")
                    folder = d.get("folderTitle", "General")
                    url = d.get("url", "")
                    print(f"  [{uid}] {title}")
                    print(f"      Folder: {folder}")
                    print(f"      URL: {url}")
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
