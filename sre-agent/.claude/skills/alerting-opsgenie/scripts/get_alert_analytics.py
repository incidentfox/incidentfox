#!/usr/bin/env python3
"""Analyze Opsgenie alert patterns for fatigue reduction.

Usage:
    python get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z" [--team-id ID]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="Get alert analytics")
    parser.add_argument("--since", required=True, help="Start date (ISO format)")
    parser.add_argument("--until", required=True, help="End date (ISO format)")
    parser.add_argument("--team-id", help="Optional team ID filter")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        date_query = f"createdAt >= {args.since} AND createdAt <= {args.until}"
        if args.team_id:
            date_query += f" AND responders:{args.team_id}"

        params = {
            "query": date_query,
            "limit": 100,
            "sort": "createdAt",
            "order": "desc",
        }
        all_alerts = []
        offset = 0

        while len(all_alerts) < 1000:
            params["offset"] = offset
            data = opsgenie_request("GET", "/v2/alerts", params=params)
            alerts = data.get("data", [])
            if not alerts:
                break

            for alert in alerts:
                mtta = None
                ack_time = alert.get("report", {}).get("ackTime")
                if ack_time:
                    mtta = ack_time / 1000 / 60
                mttr = None
                close_time = alert.get("report", {}).get("closeTime")
                if close_time:
                    mttr = close_time / 1000 / 60

                all_alerts.append(
                    {
                        "message": alert.get("message", "")[:100],
                        "acknowledged": alert.get("acknowledged", False),
                        "priority": alert.get("priority"),
                        "source": alert.get("source"),
                        "created_at": alert["createdAt"],
                        "count": alert.get("count", 1),
                        "mtta_minutes": round(mtta, 2) if mtta else None,
                        "mttr_minutes": round(mttr, 2) if mttr else None,
                    }
                )

            offset += len(alerts)
            if len(alerts) < params["limit"]:
                break

        alert_stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "acknowledged_count": 0,
                "mtta_values": [],
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
                "priorities": defaultdict(int),
                "sources": set(),
            }
        )

        for alert in all_alerts:
            msg = alert["message"]
            stats = alert_stats[msg]
            stats["fire_count"] += alert.get("count", 1)
            stats["sources"].add(alert.get("source") or "Unknown")
            stats["priorities"][alert["priority"]] += 1
            if alert["acknowledged"]:
                stats["acknowledged_count"] += 1
            if alert["mtta_minutes"]:
                stats["mtta_values"].append(alert["mtta_minutes"])
            if alert["mttr_minutes"]:
                stats["mttr_values"].append(alert["mttr_minutes"])
            try:
                created = datetime.fromisoformat(
                    alert["created_at"].replace("Z", "+00:00")
                )
                stats["hours_distribution"][created.hour] += 1
            except (ValueError, TypeError):
                pass

        analytics = []
        for msg, stats in alert_stats.items():
            fc = stats["fire_count"]
            ac = stats["acknowledged_count"]
            ack_rate = round(ac / fc * 100, 1) if fc > 0 else 0
            avg_mtta = (
                round(sum(stats["mtta_values"]) / len(stats["mtta_values"]), 2)
                if stats["mtta_values"]
                else None
            )
            avg_mttr = (
                round(sum(stats["mttr_values"]) / len(stats["mttr_values"]), 2)
                if stats["mttr_values"]
                else None
            )
            is_noisy = fc > 10 and ack_rate < 50
            is_flapping = fc > 20 and avg_mttr and avg_mttr < 10

            hours_dist = dict(stats["hours_distribution"])
            off_hours = sum(hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23])
            off_hours_rate = round(off_hours / fc * 100, 1) if fc > 0 else 0

            analytics.append(
                {
                    "alert_message": msg,
                    "fire_count": fc,
                    "acknowledgment_rate": ack_rate,
                    "avg_mtta_minutes": avg_mtta,
                    "avg_mttr_minutes": avg_mttr,
                    "sources": list(stats["sources"]),
                    "off_hours_rate": off_hours_rate,
                    "classification": {
                        "is_noisy": is_noisy,
                        "is_flapping": is_flapping,
                        "reason": (
                            "High frequency, low ack rate"
                            if is_noisy
                            else ("Quick auto-resolve" if is_flapping else None)
                        ),
                    },
                }
            )

        analytics.sort(key=lambda x: x["fire_count"], reverse=True)
        noisy = sum(1 for a in analytics if a["classification"]["is_noisy"])
        flapping = sum(1 for a in analytics if a["classification"]["is_flapping"])

        result = {
            "ok": True,
            "period": {"since": args.since, "until": args.until},
            "summary": {
                "total_unique_alerts": len(analytics),
                "total_alert_fires": len(all_alerts),
                "noisy_alerts_count": noisy,
                "flapping_alerts_count": flapping,
            },
            "alert_analytics": analytics[:50],
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Period: {args.since} to {args.until}")
            print(f"Total fires: {len(all_alerts)} | Unique alerts: {len(analytics)}")
            print(f"Noisy: {noisy} | Flapping: {flapping}")
            print()
            for a in analytics[:20]:
                flags = []
                if a["classification"]["is_noisy"]:
                    flags.append("NOISY")
                if a["classification"]["is_flapping"]:
                    flags.append("FLAPPING")
                tag = f" [{', '.join(flags)}]" if flags else ""
                print(f"  {a['fire_count']}x {a['alert_message']}{tag}")
                print(
                    f"    Ack: {a['acknowledgment_rate']}% | Off-hours: {a['off_hours_rate']}%"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
