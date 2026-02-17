#!/usr/bin/env python3
"""List all Incident.io severity levels.

Usage:
    python list_severities.py [--json]
"""

import argparse
import json
import sys

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="List severity levels")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = incidentio_request("GET", "/severities")
        severities = []
        for sev in data.get("severities", []):
            severities.append(
                {
                    "id": sev["id"],
                    "name": sev["name"],
                    "description": sev.get("description"),
                    "rank": sev.get("rank"),
                }
            )

        if args.json:
            print(json.dumps(severities, indent=2))
        else:
            print(f"Severity levels: {len(severities)}")
            for s in severities:
                print(f"  [{s['id']}] {s['name']} (rank: {s.get('rank', '?')})")
                if s.get("description"):
                    print(f"    {s['description']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
