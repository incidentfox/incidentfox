#!/usr/bin/env python3
"""Get current on-call users from Opsgenie.

Usage:
    python get_on_call.py [--schedule-id ID] [--team-id ID]
"""

import argparse
import json
import sys

from opsgenie_client import opsgenie_request


def main():
    parser = argparse.ArgumentParser(description="Get on-call users")
    parser.add_argument("--schedule-id", help="Schedule ID")
    parser.add_argument("--team-id", help="Team ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        result = []

        if args.schedule_id:
            data = opsgenie_request("GET", f"/v2/schedules/{args.schedule_id}/on-calls")
            oncall_data = data.get("data", {})
            for p in oncall_data.get("onCallParticipants", []):
                result.append(
                    {
                        "schedule_id": args.schedule_id,
                        "user": p.get("name"),
                        "type": p.get("type"),
                    }
                )
        elif args.team_id:
            data = opsgenie_request("GET", f"/v2/teams/{args.team_id}/on-calls")
            oncall_data = data.get("data", {})
            for p in oncall_data.get("onCallParticipants", []):
                result.append(
                    {
                        "team_id": args.team_id,
                        "user": p.get("name"),
                        "type": p.get("type"),
                    }
                )
        else:
            data = opsgenie_request("GET", "/v2/schedules")
            schedules = data.get("data", [])
            for schedule in schedules:
                try:
                    oncall_data = opsgenie_request(
                        "GET", f"/v2/schedules/{schedule['id']}/on-calls"
                    )
                    for p in oncall_data.get("data", {}).get("onCallParticipants", []):
                        result.append(
                            {
                                "schedule_id": schedule["id"],
                                "schedule_name": schedule["name"],
                                "user": p.get("name"),
                                "type": p.get("type"),
                            }
                        )
                except Exception:
                    continue

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"On-call entries: {len(result)}")
            for entry in result:
                schedule = (
                    entry.get("schedule_name")
                    or entry.get("schedule_id")
                    or entry.get("team_id", "")
                )
                print(
                    f"  {schedule}: {entry.get('user', 'Unknown')} ({entry.get('type', '?')})"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
