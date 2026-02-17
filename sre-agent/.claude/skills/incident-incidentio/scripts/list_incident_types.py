#!/usr/bin/env python3
"""List all Incident.io incident types.

Usage:
    python list_incident_types.py [--json]
"""

import argparse
import json
import sys

from incidentio_client import incidentio_request


def main():
    parser = argparse.ArgumentParser(description="List incident types")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = incidentio_request("GET", "/incident_types")
        types = []
        for t in data.get("incident_types", []):
            types.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "description": t.get("description"),
                    "is_default": t.get("is_default", False),
                }
            )

        if args.json:
            print(json.dumps(types, indent=2))
        else:
            print(f"Incident types: {len(types)}")
            for t in types:
                default = " (default)" if t.get("is_default") else ""
                print(f"  [{t['id']}] {t['name']}{default}")
                if t.get("description"):
                    print(f"    {t['description']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
