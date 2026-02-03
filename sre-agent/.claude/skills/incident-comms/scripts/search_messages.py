#!/usr/bin/env python3
"""Search for messages across Slack channels.

Usage:
    python search_messages.py --query SEARCH_QUERY [--count N]

Examples:
    python search_messages.py --query "error timeout"
    python search_messages.py --query "in:#incidents api error"
    python search_messages.py --query "from:@oncall database" --count 30
"""

import argparse
import json
import sys

from slack_client import format_message, search_messages


def main():
    parser = argparse.ArgumentParser(
        description="Search for messages across Slack channels"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Search query (supports Slack search operators)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of results (default: 20)",
    )
    parser.add_argument(
        "--sort",
        choices=["score", "timestamp"],
        default="timestamp",
        help="Sort field (default: timestamp)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        result = search_messages(
            query=args.query,
            count=args.count,
            sort=args.sort,
        )

        messages = result.get("messages", {}).get("matches", [])
        total = result.get("messages", {}).get("total", 0)

        if args.json:
            output = {
                "query": args.query,
                "total_matches": total,
                "returned": len(messages),
                "messages": [
                    {
                        "timestamp": m.get("ts"),
                        "user": m.get("user") or m.get("username"),
                        "channel": m.get("channel", {}).get("name"),
                        "text": m.get("text", "")[:1000],
                        "permalink": m.get("permalink"),
                    }
                    for m in messages
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print("SLACK SEARCH RESULTS")
            print("=" * 60)
            print(f"Query: {args.query}")
            print(f"Total matches: {total}")
            print(f"Showing: {len(messages)} results")
            print()

            if not messages:
                print("No messages found matching your query.")
            else:
                for msg in messages:
                    channel_name = msg.get("channel", {}).get("name", "unknown")
                    print(f"#{channel_name}")
                    print(format_message(msg))
                    if msg.get("permalink"):
                        print(f"  Link: {msg['permalink']}")
                    print("-" * 40)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
