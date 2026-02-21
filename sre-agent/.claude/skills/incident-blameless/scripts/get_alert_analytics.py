#!/usr/bin/env python3
"""Analyze Blameless incident patterns for fatigue reduction."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="Get alert analytics")
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--severity", help="Severity filter")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        params = {
            "limit": 100,
            "created_after": args.since,
            "created_before": args.until,
        }
        if args.severity:
            params["severity"] = args.severity

        all_incidents, page = [], 1
        while len(all_incidents) < 1000:
            params["page"] = page
            data = blameless_request("GET", "/incidents", params=params)
            incidents = data.get("incidents", data.get("data", []))
            if not incidents:
                break
            for inc in incidents:
                mttr = None
                c, r = inc.get("created_at", ""), inc.get("resolved_at")
                if c and r:
                    try:
                        mttr = round(
                            (
                                datetime.fromisoformat(r.replace("Z", "+00:00"))
                                - datetime.fromisoformat(c.replace("Z", "+00:00"))
                            ).total_seconds()
                            / 60,
                            2,
                        )
                    except (ValueError, KeyError, TypeError):
                        pass
                all_incidents.append(
                    {
                        "title": (inc.get("title") or "Unknown")[:100],
                        "status": inc.get("status"),
                        "severity": inc.get("severity"),
                        "created_at": c,
                        "mttr_minutes": mttr,
                    }
                )
            page += 1
            if len(incidents) < params["limit"]:
                break

        title_stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "resolved_count": 0,
                "mttr_values": [],
                "hours": defaultdict(int),
                "severities": defaultdict(int),
            }
        )
        for inc in all_incidents:
            s = title_stats[inc["title"]]
            s["fire_count"] += 1
            s["severities"][inc.get("severity") or "Unknown"] += 1
            if inc["status"] in ("resolved", "closed"):
                s["resolved_count"] += 1
            if inc["mttr_minutes"]:
                s["mttr_values"].append(inc["mttr_minutes"])
            if inc["created_at"]:
                try:
                    s["hours"][
                        datetime.fromisoformat(
                            inc["created_at"].replace("Z", "+00:00")
                        ).hour
                    ] += 1
                except (ValueError, KeyError, TypeError):
                    pass

        analytics = []
        for title, s in title_stats.items():
            fc = s["fire_count"]
            avg_mttr = (
                round(sum(s["mttr_values"]) / len(s["mttr_values"]), 2)
                if s["mttr_values"]
                else None
            )
            is_noisy = fc > 10
            is_flapping = fc > 20 and avg_mttr and avg_mttr < 10
            off_hours = sum(s["hours"].get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23])
            analytics.append(
                {
                    "incident_title": title,
                    "fire_count": fc,
                    "resolved_count": s["resolved_count"],
                    "avg_mttr_minutes": avg_mttr,
                    "off_hours_rate": round(off_hours / fc * 100, 1) if fc > 0 else 0,
                    "classification": {
                        "is_noisy": is_noisy,
                        "is_flapping": is_flapping,
                        "reason": (
                            "High frequency"
                            if is_noisy
                            else ("Quick auto-resolve" if is_flapping else None)
                        ),
                    },
                }
            )
        analytics.sort(key=lambda x: x["fire_count"], reverse=True)

        result = {
            "ok": True,
            "period": {"since": args.since, "until": args.until},
            "summary": {
                "total_unique": len(analytics),
                "total_count": len(all_incidents),
                "noisy": sum(1 for a in analytics if a["classification"]["is_noisy"]),
                "flapping": sum(
                    1 for a in analytics if a["classification"]["is_flapping"]
                ),
            },
            "alert_analytics": analytics[:50],
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Period: {args.since} to {args.until}")
            print(f"Unique: {len(analytics)} | Total: {len(all_incidents)}")
            for a in analytics[:20]:
                tag = (
                    " [NOISY]"
                    if a["classification"]["is_noisy"]
                    else (" [FLAPPING]" if a["classification"]["is_flapping"] else "")
                )
                print(f"  {a['fire_count']}x {a['incident_title']}{tag}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
