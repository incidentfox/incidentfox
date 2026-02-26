#!/usr/bin/env python3
"""List Slack channels the bot has access to.

Usage:
    python list_channels.py [--types public_channel,private_channel] [--limit N]

Examples:
    python list_channels.py
    python list_channels.py --types public_channel
    python list_channels.py --limit 500
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from slack_client import api_request


def main():
    parser = argparse.ArgumentParser(
        description="List Slack channels the bot can access"
    )
    parser.add_argument(
        "--types",
        default="public_channel,private_channel",
        help="Channel types (default: public_channel,private_channel)",
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="Max channels to return (default: 200)"
    )
    parser.add_argument(
        "--filter",
        help="Filter channels by name substring (case-insensitive)",
    )
    args = parser.parse_args()

    try:
        channels = []
        cursor = None

        while len(channels) < args.limit:
            params = {
                "types": args.types,
                "limit": min(200, args.limit - len(channels)),
                "exclude_archived": "true",
            }
            if cursor:
                params["cursor"] = cursor

            result = api_request("GET", "/conversations.list", params=params)
            batch = result.get("channels", [])
            channels.extend(batch)

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor or not batch:
                break

        # Apply name filter if specified
        if args.filter:
            filter_lower = args.filter.lower()
            channels = [
                c for c in channels if filter_lower in c.get("name", "").lower()
            ]

        if not channels:
            print("No channels found.")
            return

        print(f"CHANNELS ({len(channels)} total)")
        print("=" * 70)
        for ch in channels:
            name = ch.get("name", "unknown")
            ch_id = ch.get("id", "")
            purpose = (ch.get("purpose", {}).get("value", "") or "")[:60]
            member_count = ch.get("num_members", "?")
            is_member = "★" if ch.get("is_member") else " "

            print(f"{is_member} #{name:<30} {ch_id}  ({member_count} members)")
            if purpose:
                print(f"    {purpose}")

        print()
        print("★ = bot is a member (can read history)")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
