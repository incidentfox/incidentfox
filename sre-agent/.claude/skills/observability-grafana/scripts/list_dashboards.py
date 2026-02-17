#!/usr/bin/env python3
"""List Grafana dashboards.

Usage:
    python list_dashboards.py [--query "kubernetes"]
"""

import argparse
import json
import sys

from grafana_client import grafana_request


def main():
    parser = argparse.ArgumentParser(description="List Grafana dashboards")
    parser.add_argument("--query", default="", help="Search query")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"type": "dash-db"}
        if args.query:
            params["query"] = args.query

        data = grafana_request("GET", "api/search", params=params)
        dashboards = [
            {
                "uid": d.get("uid"),
                "title": d.get("title"),
                "folder": d.get("folderTitle", "General"),
                "url": d.get("url"),
                "tags": d.get("tags", []),
            }
            for d in data[:50]
        ]
        result = {"ok": True, "dashboards": dashboards, "count": len(dashboards)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Grafana Dashboards ({len(dashboards)} found)")
            for d in dashboards:
                tags = f" [{', '.join(d.get('tags', []))}]" if d.get("tags") else ""
                print(f"  {d.get('title', '?'):40s} ({d.get('folder', '?')}){tags}")
                print(f"    UID: {d.get('uid', '?')}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
