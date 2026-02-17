#!/usr/bin/env python3
"""List all FireHydrant environments."""

import argparse
import json
import sys

from firehydrant_client import firehydrant_request


def main():
    parser = argparse.ArgumentParser(description="List environments")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = firehydrant_request("GET", "/environments", params={"per_page": 100})
        envs = [
            {
                "id": e.get("id"),
                "name": e.get("name"),
                "description": e.get("description"),
                "slug": e.get("slug"),
                "active_incidents_count": len(e.get("active_incidents", [])),
            }
            for e in data.get("data", [])
        ]

        if args.json:
            print(json.dumps(envs, indent=2))
        else:
            print(f"Environments: {len(envs)}")
            for e in envs:
                print(
                    f"  {e['name']} ({e.get('slug', '')}) - {e['active_incidents_count']} active incidents"
                )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
