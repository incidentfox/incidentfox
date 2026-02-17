#!/usr/bin/env python3
"""Get active Grafana alerts.

Usage:
    python get_alerts.py
"""

import argparse
import json
import sys

from grafana_client import grafana_request


def main():
    parser = argparse.ArgumentParser(description="Get Grafana alerts")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = grafana_request("GET", "api/alerts")
        alerts = [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "state": a.get("state"),
                "dashboard_uid": a.get("dashboardUid"),
                "panel_id": a.get("panelId"),
            }
            for a in data[:50]
        ]
        result = {"ok": True, "alerts": alerts, "count": len(alerts)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Grafana Alerts ({len(alerts)})")
            if not alerts:
                print("  No active alerts")
            for a in alerts:
                print(f"  [{a.get('state', '?').upper()}] {a.get('name', '?')}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
