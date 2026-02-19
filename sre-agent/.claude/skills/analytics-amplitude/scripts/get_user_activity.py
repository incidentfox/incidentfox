#!/usr/bin/env python3
"""Get Amplitude user activity stream.

Usage:
    python get_user_activity.py --user "user@example.com"
    python get_user_activity.py --user "12345" --offset 0 --limit 50
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from amplitude_client import amplitude_request


def main():
    parser = argparse.ArgumentParser(description="Get Amplitude user activity")
    parser.add_argument("--user", required=True, help="Amplitude user ID or email")
    parser.add_argument(
        "--offset", type=int, default=0, help="Pagination offset (default: 0)"
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Max events to return (default: 100)"
    )
    parser.add_argument("--raw", action="store_true", help="Output raw JSON response")
    args = parser.parse_args()

    params = {
        "user": args.user,
        "offset": args.offset,
        "limit": args.limit,
    }

    data = amplitude_request("GET", "/useractivity", params=params)

    if args.raw:
        print(json.dumps(data, indent=2))
        return

    events = data.get("userData", {}).get("events", [])
    user_id = data.get("userData", {}).get("user_id", args.user)

    print(f"User: {user_id}")
    print(f"Events: {len(events)} (offset={args.offset}, limit={args.limit})")
    print("---")

    if not events:
        print("No events found for this user.")
        return

    for event in events:
        event_type = event.get("event_type", "unknown")
        event_time = event.get("event_time", "")
        platform = event.get("platform", "")
        country = event.get("country", "")
        city = event.get("city", "")

        line = f"  [{event_time}] {event_type}"
        details = []
        if platform:
            details.append(f"platform={platform}")
        if country:
            details.append(f"country={country}")
        if city:
            details.append(f"city={city}")
        if details:
            line += f" ({', '.join(details)})"

        event_props = event.get("event_properties", {})
        if event_props:
            props_str = json.dumps(event_props, default=str)
            if len(props_str) > 200:
                props_str = props_str[:200] + "..."
            line += f"\n    props: {props_str}"

        print(line)


if __name__ == "__main__":
    main()
