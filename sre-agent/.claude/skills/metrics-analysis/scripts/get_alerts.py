#!/usr/bin/env python3
"""Get Grafana alerts and their current state.

Usage:
    python get_alerts.py [--state STATE]

Examples:
    python get_alerts.py
    python get_alerts.py --state alerting
    python get_alerts.py --state pending
"""

import argparse
import json
import sys

from grafana_client import get_alerts


def main():
    parser = argparse.ArgumentParser(
        description="Get Grafana alerts"
    )
    parser.add_argument(
        "--state",
        choices=["alerting", "pending", "ok", "paused", "no_data"],
        help="Filter by alert state",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        alerts = get_alerts(state=args.state)

        if args.json:
            print(json.dumps(alerts, indent=2))
        else:
            print("=" * 60)
            print("GRAFANA ALERTS")
            if args.state:
                print(f"Filter: state={args.state}")
            print("=" * 60)
            print(f"Found: {len(alerts)} alerts")
            print()

            # Group by state
            by_state = {}
            for alert in alerts:
                state = alert.get("state", "unknown")
                if state not in by_state:
                    by_state[state] = []
                by_state[state].append(alert)

            for state, state_alerts in sorted(by_state.items()):
                state_icon = {
                    "alerting": "🔴",
                    "pending": "🟡",
                    "ok": "🟢",
                    "paused": "⏸️",
                    "no_data": "⚪",
                }.get(state, "❓")

                print(f"{state_icon} {state.upper()} ({len(state_alerts)})")
                print("-" * 40)
                for alert in state_alerts:
                    name = alert.get("name", "Unnamed")
                    dashboard = alert.get("dashboardSlug", "")
                    panel = alert.get("panelId", "")
                    print(f"  • {name}")
                    if dashboard:
                        print(f"    Dashboard: {dashboard}, Panel: {panel}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
