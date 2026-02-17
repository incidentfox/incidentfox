#!/usr/bin/env python3
"""List Incident.io incidents with optional filters.

Usage:
    python list_incidents.py [--status active] [--severity-id ID] [--max-results 100]
"""

import argparse
import json
import sys

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="List Incident.io incidents")
    parser.add_argument(
        "--status", help="Filter by status (triage, active, resolved, closed)"
    )
    parser.add_argument("--severity-id", help="Filter by severity ID")
    parser.add_argument(
        "--max-results", type=int, default=100, help="Maximum results (default: 100)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"page_size": min(args.max_results, 100)}
        if args.status:
            params["status"] = args.status
        if args.severity_id:
            params["severity_id"] = args.severity_id

        all_incidents = []
        next_cursor = None

        while len(all_incidents) < args.max_results:
            if next_cursor:
                params["after"] = next_cursor

            data = incidentio_request("GET", "/incidents", params=params)
            incidents = data.get("incidents", [])

            if not incidents:
                break

            for inc in incidents:
                all_incidents.append(
                    {
                        "id": inc["id"],
                        "name": inc.get("name"),
                        "reference": inc.get("reference"),
                        "status": inc.get("status", {}).get("category"),
                        "severity": inc.get("severity", {}).get("name"),
                        "created_at": inc.get("created_at"),
                        "updated_at": inc.get("updated_at"),
                        "summary": inc.get("summary"),
                        "incident_lead": inc.get("incident_lead", {}).get("name"),
                        "url": inc.get("permalink"),
                    }
                )

            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        by_status = {}
        by_severity = {}
        for inc in all_incidents:
            s = inc.get("status") or "unknown"
            by_status[s] = by_status.get(s, 0) + 1
            sev = inc.get("severity") or "unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1

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
            if by_status:
                print(
                    f"By status: {', '.join(f'{k}: {v}' for k, v in by_status.items())}"
                )
            if by_severity:
                print(
                    f"By severity: {', '.join(f'{k}: {v}' for k, v in by_severity.items())}"
                )
            print()
            for inc in all_incidents:
                print(
                    f"  [{inc.get('status', '?')}] {inc.get('reference', '')} - {inc.get('name', '')}"
                )
                print(
                    f"    Severity: {inc.get('severity', '?')} | Lead: {inc.get('incident_lead', 'Unassigned')}"
                )
                if inc.get("url"):
                    print(f"    URL: {inc['url']}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
