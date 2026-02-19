#!/usr/bin/env python3
"""Get active Grafana alerts.

Supports both legacy alerting (/api/alerts) and unified alerting
(/api/alertmanager/grafana/api/v2/alerts) used by Grafana Cloud.

Usage:
    python get_alerts.py
"""

import argparse
import json
import sys

from grafana_client import grafana_request


def get_unified_alerts():
    """Try unified alerting API (Grafana Cloud / Grafana 9+)."""
    data = grafana_request("GET", "api/alertmanager/grafana/api/v2/alerts")
    return [
        {
            "name": a.get("labels", {}).get("alertname", "?"),
            "state": a.get("status", {}).get("state", "?"),
            "severity": a.get("labels", {}).get("severity", ""),
            "summary": a.get("annotations", {}).get("summary", ""),
            "starts_at": a.get("startsAt", ""),
        }
        for a in data[:50]
    ]


def get_legacy_alerts():
    """Try legacy alerting API (Grafana < 9)."""
    data = grafana_request("GET", "api/alerts")
    return [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "state": a.get("state"),
            "dashboard_uid": a.get("dashboardUid"),
            "panel_id": a.get("panelId"),
        }
        for a in data[:50]
    ]


def main():
    parser = argparse.ArgumentParser(description="Get Grafana alerts")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Try unified alerting first (Grafana Cloud), fall back to legacy
        try:
            alerts = get_unified_alerts()
        except Exception:
            alerts = get_legacy_alerts()

        result = {"ok": True, "alerts": alerts, "count": len(alerts)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Grafana Alerts ({len(alerts)})")
            if not alerts:
                print("  No active alerts")
            for a in alerts:
                state = a.get("state", "?").upper()
                name = a.get("name", "?")
                severity = a.get("severity", "")
                suffix = f" [{severity}]" if severity else ""
                print(f"  [{state}] {name}{suffix}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
