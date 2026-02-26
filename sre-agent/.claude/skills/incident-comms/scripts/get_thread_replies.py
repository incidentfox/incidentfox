#!/usr/bin/env python3
"""Get replies in a Slack thread.

Usage:
    python get_thread_replies.py --channel CHANNEL_ID --thread THREAD_TS [--limit N]

Examples:
    python get_thread_replies.py --channel C123ABC456 --thread 1705320123.456789
    python get_thread_replies.py --channel C123ABC456 --thread 1705320123.456789 --limit 50
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from slack_client import format_message, get_thread_replies


def main():
    parser = argparse.ArgumentParser(description="Get replies in a Slack thread")
    parser.add_argument(
        "--channel", required=True, help="Channel ID (e.g., C123ABC456)"
    )
    parser.add_argument(
        "--thread",
        required=True,
        help="Thread parent timestamp (e.g., 1705320123.456789)",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Max replies to return (default: 100)"
    )
    args = parser.parse_args()

    try:
        result = get_thread_replies(args.channel, args.thread, limit=args.limit)
        messages = result.get("messages", [])

        if not messages:
            print("No messages found in this thread.")
            return

        print(f"THREAD REPLIES ({len(messages)} messages)")
        print("=" * 70)
        for msg in messages:
            print(format_message(msg))
            print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
