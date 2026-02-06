#!/usr/bin/env python3
"""Add a comment to a ClickUp task.

Use this to document investigation findings on incident tasks.

Usage:
    python add_comment.py TASK_ID --message "Comment text"

Examples:
    python add_comment.py abc123 --message "Found root cause in logs"
    python add_comment.py abc123 -m "Restarting service to mitigate"
    python add_comment.py abc123 --message "## Investigation Summary\\n- Found error in API logs"
"""

import argparse
import json
import sys

from clickup_client import create_task_comment


def main():
    parser = argparse.ArgumentParser(description="Add comment to ClickUp task")
    parser.add_argument("task_id", help="Task ID to comment on")
    parser.add_argument(
        "--message", "-m", required=True, help="Comment text (supports markdown)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Create comment
        comment = create_task_comment(args.task_id, args.message)

        if args.json:
            print(json.dumps(comment, indent=2))
        else:
            print("Comment added successfully!")
            print()
            print(f"Task ID: {args.task_id}")
            print(f"Comment ID: {comment.get('id', 'N/A')}")
            print()
            print("Comment text:")
            print("-" * 40)
            print(args.message)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
