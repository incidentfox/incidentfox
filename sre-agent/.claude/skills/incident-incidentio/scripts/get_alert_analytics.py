#!/usr/bin/env python3
"""Analyze Incident.io alert patterns for fatigue reduction.

Usage:
    python get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="Get alert analytics")
    parser.add_argument("--since", required=True, help="Start date (ISO format)")
    parser.add_argument("--until", required=True, help="End date (ISO format)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {
            "page_size": 100,
            "created_at[gte]": args.since,
            "created_at[lte]": args.until,
        }

        all_alerts = []
        next_cursor = None

        while True:
            if next_cursor:
                params["after"] = next_cursor

            data = incidentio_request("GET", "/alerts", params=params)
            alerts = data.get("alerts", [])

            if not alerts:
                break

            all_alerts.extend(alerts)

            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        route_stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "acknowledged_count": 0,
                "hours_distribution": defaultdict(int),
            }
        )

        for alert in all_alerts:
            route = alert.get("alert_route", {}).get("name", "Unknown")
            stats = route_stats[route]
            stats["fire_count"] += 1
            if alert.get("status") == "acknowledged":
                stats["acknowledged_count"] += 1
            created = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
            stats["hours_distribution"][created.hour] += 1

        route_analytics = []
        for route, stats in route_stats.items():
            fire_count = stats["fire_count"]
            ack_count = stats["acknowledged_count"]
            ack_rate = round(ack_count / fire_count * 100, 1) if fire_count > 0 else 0

            hours_dist = dict(stats["hours_distribution"])
            off_hours_count = sum(
                hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23]
            )
            off_hours_rate = (
                round(off_hours_count / fire_count * 100, 1) if fire_count > 0 else 0
            )

            is_noisy = fire_count > 10 and ack_rate < 50

            route_analytics.append(
                {
                    "route": route,
                    "fire_count": fire_count,
                    "acknowledgment_rate": ack_rate,
                    "off_hours_rate": off_hours_rate,
                    "classification": {
                        "is_noisy": is_noisy,
                        "reason": "High frequency, low ack rate" if is_noisy else None,
                    },
                }
            )

        route_analytics.sort(key=lambda x: x["fire_count"], reverse=True)
        noisy_routes = sum(
            1 for r in route_analytics if r["classification"]["is_noisy"]
        )

        result = {
            "ok": True,
            "period": {"since": args.since, "until": args.until},
            "summary": {
                "total_alerts": len(all_alerts),
                "unique_routes": len(route_analytics),
                "noisy_routes_count": noisy_routes,
            },
            "route_analytics": route_analytics[:30],
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Period: {args.since} to {args.until}")
            print(f"Total alerts: {len(all_alerts)}")
            print(f"Unique routes: {len(route_analytics)}")
            print(f"Noisy routes: {noisy_routes}")
            print()
            for r in route_analytics[:20]:
                noisy = " [NOISY]" if r["classification"]["is_noisy"] else ""
                print(
                    f"  {r['route']}: {r['fire_count']} fires, {r['acknowledgment_rate']}% ack rate{noisy}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
