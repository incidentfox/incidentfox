#!/usr/bin/env python3
"""List Blameless incidents with optional filters."""

import argparse
import json
import sys

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="List Blameless incidents")
    parser.add_argument(
        "--status", help="Filter: investigating, identified, monitoring, resolved"
    )
    parser.add_argument("--severity", help="Filter: SEV0-SEV4")
    parser.add_argument("--incident-type", help="Filter by incident type")
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        params = {"limit": min(args.max_results, 100)}
        if args.status:
            params["status"] = args.status
        if args.severity:
            params["severity"] = args.severity
        if args.incident_type:
            params["type"] = args.incident_type

        all_incidents, page = [], 1
        while len(all_incidents) < args.max_results:
            params["page"] = page
            data = blameless_request("GET", "/incidents", params=params)
            incidents = data.get("incidents", data.get("data", []))
            if not incidents:
                break
            for inc in incidents:
                all_incidents.append(
                    {
                        "id": inc.get("id"),
                        "title": inc.get("title") or inc.get("name"),
                        "status": inc.get("status"),
                        "severity": inc.get("severity"),
                        "created_at": inc.get("created_at"),
                        "resolved_at": inc.get("resolved_at"),
                        "commander": (
                            inc.get("commander", {}).get("name")
                            if isinstance(inc.get("commander"), dict)
                            else inc.get("commander")
                        ),
                        "url": inc.get("url") or inc.get("permalink"),
                    }
                )
            page += 1
            if len(incidents) < params["limit"]:
                break

        by_status, by_severity = {}, {}
        for i in all_incidents:
            by_status[i["status"] or "unknown"] = (
                by_status.get(i["status"] or "unknown", 0) + 1
            )
            by_severity[i["severity"] or "unknown"] = (
                by_severity.get(i["severity"] or "unknown", 0) + 1
            )

        result = {
            "ok": True,
            "total_count": len(all_incidents),
            "summary": {"by_status": by_status, "by_severity": by_severity},
            "incidents": all_incidents,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Found: {len(all_incidents)} incidents")
            for i in all_incidents:
                print(
                    f"  [{i.get('severity', '?')}] {i.get('title', '')} - {i.get('status', '?')}"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
