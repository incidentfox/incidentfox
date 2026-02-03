#!/usr/bin/env python3
"""Post a message to a Slack channel.

Usage:
    python post_message.py --channel CHANNEL_ID --text MESSAGE [--thread THREAD_TS]

Examples:
    python post_message.py --channel C123ABC456 --text "Investigation update: found root cause"
    python post_message.py --channel C123ABC456 --text "Rollback completed" --thread 1705320123.456789
"""

import argparse
import json
import sys

from slack_client import post_message


def main():
    parser = argparse.ArgumentParser(description="Post a message to a Slack channel")
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel ID (e.g., C123ABC456)",
    )
    parser.add_argument(
        "--text",
        required=True,
        help="Message text (supports Slack markdown)",
    )
    parser.add_argument(
        "--thread",
        help="Thread timestamp to reply to",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        result = post_message(
            channel_id=args.channel,
            text=args.text,
            thread_ts=args.thread,
        )

        message = result.get("message", {})

        if args.json:
            output = {
                "success": True,
                "channel": result.get("channel"),
                "timestamp": message.get("ts"),
                "text": message.get("text"),
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print("MESSAGE POSTED SUCCESSFULLY")
            print("=" * 60)
            print(f"Channel: {result.get('channel')}")
            print(f"Timestamp: {message.get('ts')}")
            if args.thread:
                print(f"Thread: {args.thread}")
            print()
            print("Message:")
            print("-" * 40)
            print(message.get("text", args.text))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
