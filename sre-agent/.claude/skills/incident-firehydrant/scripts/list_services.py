#!/usr/bin/env python3
"""List all FireHydrant services."""

import argparse
import json
import sys

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="List services")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        all_services, page = [], 1
        while True:
            data = firehydrant_request(
                "GET", "/services", params={"per_page": 100, "page": page}
            )
            services = data.get("data", [])
            if not services:
                break
            for s in services:
                all_services.append(
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "description": s.get("description"),
                        "tier": s.get("service_tier"),
                        "owner": (
                            s.get("owner", {}).get("name")
                            if isinstance(s.get("owner"), dict)
                            else None
                        ),
                        "labels": s.get("labels", {}),
                        "active_incidents_count": (
                            len(s.get("active_incidents", []))
                            if isinstance(s.get("active_incidents"), list)
                            else 0
                        ),
                    }
                )
            page += 1
            if len(services) < 100:
                break

        if args.json:
            print(json.dumps(all_services, indent=2))
        else:
            print(f"Services: {len(all_services)}")
            for s in all_services:
                print(
                    f"  {s['name']} (tier: {s.get('tier', '?')}, owner: {s.get('owner', '?')})"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
