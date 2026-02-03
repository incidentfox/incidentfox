#!/usr/bin/env python3
"""Get message history from a Slack channel.

Usage:
    python get_channel_history.py --channel CHANNEL_ID [--limit N]

Examples:
    python get_channel_history.py --channel C123ABC456
    python get_channel_history.py --channel C123ABC456 --limit 50
"""

import argparse
import json
import sys

from slack_client import format_message, get_channel_history


def main():
    parser = argparse.ArgumentParser(
        description="Get message history from a Slack channel"
    )
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel ID (e.g., C123ABC456)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum messages to return (default: 50)",
    )
    parser.add_argument(
        "--oldest",
        help="Start timestamp (Unix)",
    )
    parser.add_argument(
        "--latest",
        help="End timestamp (Unix)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        result = get_channel_history(
            channel_id=args.channel,
            limit=args.limit,
            oldest=args.oldest,
            latest=args.latest,
        )

        messages = result.get("messages", [])
        has_more = result.get("has_more", False)

        if args.json:
            output = {
                "channel_id": args.channel,
                "message_count": len(messages),
                "has_more": has_more,
                "messages": [
                    {
                        "timestamp": m.get("ts"),
                        "user": m.get("user"),
                        "text": m.get("text", "")[:1000],
                        "thread_ts": m.get("thread_ts"),
                        "reply_count": m.get("reply_count", 0),
                    }
                    for m in messages
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print(f"CHANNEL HISTORY: {args.channel}")
            print("=" * 60)
            print(f"Messages: {len(messages)}")
            print(f"Has more: {has_more}")
            print()

            if not messages:
                print("No messages found in channel.")
            else:
                # Messages are in reverse chronological order
                for msg in reversed(messages):
                    print(format_message(msg))
                    if msg.get("thread_ts") and msg.get("reply_count"):
                        print(
                            f"  └── Thread with {msg['reply_count']} replies (ts: {msg['thread_ts']})"
                        )
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
