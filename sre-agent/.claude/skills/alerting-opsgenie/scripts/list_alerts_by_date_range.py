#!/usr/bin/env python3
"""List Opsgenie alerts within a date range with MTTA/MTTR computation.

Usage:
    python list_alerts_by_date_range.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
"""

import argparse
import json
import sys
from datetime import datetime

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="List alerts by date range")
    parser.add_argument("--since", required=True, help="Start date (ISO format)")
    parser.add_argument("--until", required=True, help="End date (ISO format)")
    parser.add_argument("--query", help="Optional Opsgenie search query")
    parser.add_argument("--max-results", type=int, default=500, help="Maximum results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        date_query = f"createdAt >= {args.since} AND createdAt <= {args.until}"
        if args.query:
            date_query = f"({date_query}) AND ({args.query})"

        params = {
            "query": date_query,
            "limit": 100,
            "sort": "createdAt",
            "order": "desc",
        }

        all_alerts = []
        offset = 0

        while len(all_alerts) < args.max_results:
            params["offset"] = offset
            data = opsgenie_request("GET", "/v2/alerts", params=params)
            alerts = data.get("data", [])

            if not alerts:
                break

            for alert in alerts:
                mtta_minutes = None
                ack_time = alert.get("report", {}).get("ackTime")
                if ack_time:
                    mtta_minutes = ack_time / 1000 / 60

                mttr_minutes = None
                close_time = alert.get("report", {}).get("closeTime")
                if close_time:
                    mttr_minutes = close_time / 1000 / 60

                all_alerts.append(
                    {
                        "id": alert["id"],
                        "tiny_id": alert.get("tinyId"),
                        "message": alert.get("message"),
                        "status": alert.get("status"),
                        "acknowledged": alert.get("acknowledged", False),
                        "priority": alert.get("priority"),
                        "source": alert.get("source"),
                        "created_at": alert["createdAt"],
                        "mtta_minutes": (
                            round(mtta_minutes, 2) if mtta_minutes else None
                        ),
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                        "count": alert.get("count", 1),
                        "tags": alert.get("tags", []),
                        "teams": [t.get("name") for t in alert.get("teams", [])],
                    }
                )

            offset += len(alerts)
            if len(alerts) < params["limit"]:
                break

        total = len(all_alerts)
        ack_count = sum(1 for a in all_alerts if a["acknowledged"])
        mtta_values = [a["mtta_minutes"] for a in all_alerts if a["mtta_minutes"]]
        mttr_values = [a["mttr_minutes"] for a in all_alerts if a["mttr_minutes"]]

        by_message = {}
        for a in all_alerts:
            msg = a["message"][:100]
            by_message[msg] = by_message.get(msg, 0) + 1
        top_alerts = sorted(by_message.items(), key=lambda x: x[1], reverse=True)[:20]

        by_priority = {}
        for a in all_alerts:
            by_priority[a["priority"]] = by_priority.get(a["priority"], 0) + 1

        result = {
            "ok": True,
            "period": {"since": args.since, "until": args.until},
            "total_alerts": total,
            "summary": {
                "acknowledged_count": ack_count,
                "acknowledged_rate": (
                    round(ack_count / total * 100, 1) if total > 0 else 0
                ),
                "avg_mtta_minutes": (
                    round(sum(mtta_values) / len(mtta_values), 2)
                    if mtta_values
                    else None
                ),
                "avg_mttr_minutes": (
                    round(sum(mttr_values) / len(mttr_values), 2)
                    if mttr_values
                    else None
                ),
            },
            "by_priority": by_priority,
            "top_alerts": top_alerts,
            "alerts": all_alerts,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Period: {args.since} to {args.until}")
            print(f"Total alerts: {total}")
            print(f"Ack rate: {result['summary']['acknowledged_rate']}%")
            if result["summary"]["avg_mtta_minutes"]:
                print(f"Avg MTTA: {result['summary']['avg_mtta_minutes']} min")
            if result["summary"]["avg_mttr_minutes"]:
                print(f"Avg MTTR: {result['summary']['avg_mttr_minutes']} min")
            print(
                f"By priority: {', '.join(f'{k}: {v}' for k, v in by_priority.items())}"
            )
            if top_alerts:
                print("\nTop alerts by frequency:")
                for msg, count in top_alerts[:10]:
                    print(f"  {count}x {msg}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
