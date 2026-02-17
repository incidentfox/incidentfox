#!/usr/bin/env python3
"""List all Opsgenie teams.

Usage:
    python list_teams.py [--json]
"""

import argparse
import json
import sys

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="List Opsgenie teams")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = opsgenie_request("GET", "/v2/teams")
        teams = []
        for team in data.get("data", []):
            teams.append(
                {
                    "id": team["id"],
                    "name": team["name"],
                    "description": team.get("description"),
                }
            )

        if args.json:
            print(json.dumps(teams, indent=2))
        else:
            print(f"Teams: {len(teams)}")
            for t in teams:
                print(f"  [{t['id']}] {t['name']}")
                if t.get("description"):
                    print(f"    {t['description']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
