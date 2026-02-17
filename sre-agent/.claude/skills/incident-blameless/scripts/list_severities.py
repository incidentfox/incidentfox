#!/usr/bin/env python3
"""List all Blameless severity levels."""

import argparse
import json
import sys

from blameless_client import blameless_request


def main():
    parser = argparse.ArgumentParser(description="List severities")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        data = blameless_request("GET", "/severities")
        severities = [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "description": s.get("description"),
                "rank": s.get("rank") or s.get("order"),
            }
            for s in data.get("severities", data.get("data", []))
        ]

        if args.json:
            print(json.dumps(severities, indent=2))
        else:
            print(f"Severities: {len(severities)}")
            for s in severities:
                print(f"  [{s['id']}] {s['name']} (rank: {s.get('rank', '?')})")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
