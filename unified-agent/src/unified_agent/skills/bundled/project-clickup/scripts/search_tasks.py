#!/usr/bin/env python3
"""Search for tasks in ClickUp.

Use this to find tasks by name, description, or other criteria.

Usage:
    python search_tasks.py [--query QUERY] [--status STATUS] [options]

Examples:
    python search_tasks.py --query "payment"
    python search_tasks.py --query "incident" --status "investigating"
    python search_tasks.py --updated-since 24h --json
"""

import argparse
import json
import sys
import time

from clickup_client import format_task, search_tasks


def parse_time_range(time_str: str) -> int:
    """Parse time range string to Unix milliseconds.

    Args:
        time_str: Time string like "1h", "24h", "7d"

    Returns:
        Unix timestamp in milliseconds
    """
    now = int(time.time() * 1000)

    if time_str.endswith("h"):
        hours = int(time_str[:-1])
        return now - (hours * 60 * 60 * 1000)
    elif time_str.endswith("d"):
        days = int(time_str[:-1])
        return now - (days * 24 * 60 * 60 * 1000)
    elif time_str.endswith("m"):
        minutes = int(time_str[:-1])
        return now - (minutes * 60 * 1000)
    else:
        raise ValueError(f"Invalid time format: {time_str}. Use 1h, 24h, 7d, etc.")


def main():
    parser = argparse.ArgumentParser(description="Search ClickUp tasks")
    parser.add_argument(
        "--query", "-q", help="Search query (matches name and description)"
    )
    parser.add_argument(
        "--status", "-s", action="append", help="Filter by status (can repeat)"
    )
    parser.add_argument(
        "--assignee", "-a", action="append", help="Filter by assignee ID (can repeat)"
    )
    parser.add_argument(
        "--list-id", action="append", help="Filter by list ID (can repeat)"
    )
    parser.add_argument(
        "--space-id", action="append", help="Filter by space ID (can repeat)"
    )
    parser.add_argument(
        "--updated-since",
        help="Only tasks updated since (e.g., '1h', '24h', '7d')",
    )
    parser.add_argument(
        "--created-since",
        help="Only tasks created since (e.g., '1h', '24h', '7d')",
    )
    parser.add_argument(
        "--include-closed", action="store_true", help="Include closed tasks"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum results (default: 50)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build search parameters
        params = {
            "include_closed": args.include_closed,
        }

        if args.query:
            params["query"] = args.query
        if args.status:
            params["statuses"] = args.status
        if args.assignee:
            params["assignees"] = args.assignee
        if args.list_id:
            params["list_ids"] = args.list_id
        if args.space_id:
            params["space_ids"] = args.space_id
        if args.updated_since:
            params["date_updated_gt"] = parse_time_range(args.updated_since)
        if args.created_since:
            params["date_created_gt"] = parse_time_range(args.created_since)

        # Search
        tasks = search_tasks(**params)

        # Limit results
        tasks = tasks[: args.limit]

        if args.json:
            print(json.dumps(tasks, indent=2))
        else:
            print("=" * 60)
            print("CLICKUP TASK SEARCH")
            print("=" * 60)
            print()

            if args.query:
                print(f"Query: {args.query}")
            if args.status:
                print(f"Status filter: {', '.join(args.status)}")
            if args.updated_since:
                print(f"Updated since: {args.updated_since}")
            print()

            if not tasks:
                print("No tasks found matching criteria.")
            else:
                print(f"Found {len(tasks)} task(s):")
                print("-" * 40)

                for task in tasks:
                    print()
                    print(format_task(task, verbose=True))
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
