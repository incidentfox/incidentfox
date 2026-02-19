#!/usr/bin/env python3
"""Analyze FireHydrant incident patterns for fatigue reduction."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="Get alert analytics")
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--service-id", help="Optional service ID filter")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        params = {"per_page": 100, "start_date": args.since, "end_date": args.until}
        all_incidents, page = [], 1
        while len(all_incidents) < 1000:
            params["page"] = page
            data = firehydrant_request("GET", "/incidents", params=params)
            incidents = data.get("data", [])
            if not incidents:
                break
            for inc in incidents:
                resolved_at = None
                for ms in inc.get("milestones", []):
                    if (ms.get("type") or ms.get("slug")) == "resolved":
                        resolved_at = ms.get("occurred_at") or ms.get("created_at")
                mttr = None
                start = inc.get("started_at") or inc.get("created_at", "")
                if start and resolved_at:
                    try:
                        mttr = round(
                            (
                                datetime.fromisoformat(
                                    resolved_at.replace("Z", "+00:00")
                                )
                                - datetime.fromisoformat(start.replace("Z", "+00:00"))
                            ).total_seconds()
                            / 60,
                            2,
                        )
                    except (ValueError, KeyError, TypeError):
                        pass
                all_incidents.append(
                    {
                        "name": (inc.get("name") or "Unknown")[:100],
                        "status": inc.get("current_milestone"),
                        "severity": inc.get("severity"),
                        "created_at": inc.get("created_at"),
                        "mttr_minutes": mttr,
                        "services": [s.get("name") for s in inc.get("services", [])],
                    }
                )
            page += 1
            if len(incidents) < params["per_page"]:
                break

        stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "resolved_count": 0,
                "mttr_values": [],
                "hours": defaultdict(int),
                "services": set(),
            }
        )
        for inc in all_incidents:
            s = stats[inc["name"]]
            s["fire_count"] += 1
            for svc in inc.get("services", []):
                s["services"].add(svc)
            if inc["status"] in ("resolved", "closed", "post_incident"):
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
        for name, s in stats.items():
            fc = s["fire_count"]
            avg_mttr = (
                round(sum(s["mttr_values"]) / len(s["mttr_values"]), 2)
                if s["mttr_values"]
                else None
            )
            is_noisy = fc > 10
            is_flapping = fc > 20 and avg_mttr and avg_mttr < 10
            off = sum(s["hours"].get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23])
            analytics.append(
                {
                    "incident_name": name,
                    "fire_count": fc,
                    "avg_mttr_minutes": avg_mttr,
                    "services": list(s["services"]),
                    "off_hours_rate": round(off / fc * 100, 1) if fc > 0 else 0,
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
            },
            "alert_analytics": analytics[:50],
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Total: {len(all_incidents)} | Unique: {len(analytics)}")
            for a in analytics[:20]:
                tag = " [NOISY]" if a["classification"]["is_noisy"] else ""
                print(f"  {a['fire_count']}x {a['incident_name']}{tag}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
