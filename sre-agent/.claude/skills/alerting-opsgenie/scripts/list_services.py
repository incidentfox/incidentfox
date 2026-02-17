#!/usr/bin/env python3
"""List all Opsgenie services.

Usage:
    python list_services.py [--json]
"""

import argparse
import json
import sys

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="List Opsgenie services")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        all_services = []
        offset = 0

        while True:
            data = opsgenie_request(
                "GET", "/v1/services", params={"limit": 100, "offset": offset}
            )
            services = data.get("data", [])

            if not services:
                break

            for svc in services:
                all_services.append(
                    {
                        "id": svc["id"],
                        "name": svc["name"],
                        "description": svc.get("description"),
                        "team_id": svc.get("teamId"),
                    }
                )

            offset += 100
            if len(services) < 100:
                break

        if args.json:
            print(json.dumps(all_services, indent=2))
        else:
            print(f"Services: {len(all_services)}")
            for svc in all_services:
                print(f"  [{svc['id']}] {svc['name']}")
                if svc.get("description"):
                    print(f"    {svc['description']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
