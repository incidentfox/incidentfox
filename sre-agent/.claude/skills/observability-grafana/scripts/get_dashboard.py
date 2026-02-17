#!/usr/bin/env python3
"""Get a specific Grafana dashboard with panels.

Usage:
    python get_dashboard.py --uid DASHBOARD_UID
"""

import argparse
import json
import sys

from grafana_client import grafana_request


def main():
    parser = argparse.ArgumentParser(description="Get Grafana dashboard details")
    parser.add_argument("--uid", required=True, help="Dashboard UID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = grafana_request("GET", f"api/dashboards/uid/{args.uid}")
        dashboard = data.get("dashboard", {})
        panels = [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "type": p.get("type"),
                "datasource": p.get("datasource"),
            }
            for p in dashboard.get("panels", [])
        ]

        result = {
            "ok": True,
            "uid": dashboard.get("uid"),
            "title": dashboard.get("title"),
            "tags": dashboard.get("tags", []),
            "panel_count": len(panels),
            "panels": panels,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"Dashboard: {result.get('title', '?')} (UID: {result.get('uid', '?')})"
            )
            print(f"\nPanels ({len(panels)}):")
            for p in panels:
                print(f"  {p.get('title', '?'):40s} ({p.get('type', '?')})")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
