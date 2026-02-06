#!/usr/bin/env python3
"""Get detailed information about a ClickUp task.

Use this to view full task details including description, comments, and subtasks.

Usage:
    python get_task.py TASK_ID [options]

Examples:
    python get_task.py abc123
    python get_task.py abc123 --include-comments
    python get_task.py abc123 --include-subtasks --json
"""

import argparse
import json
import sys
from datetime import datetime

from clickup_client import get_task, get_task_comments


def format_comment(comment: dict) -> str:
    """Format a comment for display."""
    user = comment.get("user", {})
    username = user.get("username", user.get("email", "Unknown"))
    date = comment.get("date")
    text = comment.get("comment_text", "")

    date_str = ""
    if date:
        dt = datetime.fromtimestamp(int(date) / 1000)
        date_str = dt.strftime("%Y-%m-%d %H:%M")

    return f"  [{date_str}] {username}:\n    {text}"


def main():
    parser = argparse.ArgumentParser(description="Get ClickUp task details")
    parser.add_argument("task_id", help="Task ID to retrieve")
    parser.add_argument(
        "--include-comments", "-c", action="store_true", help="Include task comments"
    )
    parser.add_argument(
        "--include-subtasks", "-s", action="store_true", help="Include subtasks"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Get task
        task = get_task(args.task_id, include_subtasks=args.include_subtasks)

        # Get comments if requested
        comments = []
        if args.include_comments:
            comments = get_task_comments(args.task_id)

        if args.json:
            result = {"task": task}
            if args.include_comments:
                result["comments"] = comments
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("CLICKUP TASK DETAILS")
            print("=" * 60)
            print()

            # Basic info
            print(f"Name: {task.get('name', 'Untitled')}")
            print(f"ID: {task.get('id', '')}")
            print(f"URL: {task.get('url', '')}")
            print()

            # Status and priority
            status = task.get("status", {}).get("status", "Unknown")
            print(f"Status: {status}")

            priority = task.get("priority")
            if priority:
                priority_map = {1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
                print(f"Priority: {priority_map.get(priority.get('id'), 'Normal')}")

            # Assignees
            assignees = task.get("assignees", [])
            if assignees:
                names = [
                    a.get("username", a.get("email", "Unknown")) for a in assignees
                ]
                print(f"Assignees: {', '.join(names)}")

            # Dates
            created = task.get("date_created")
            if created:
                dt = datetime.fromtimestamp(int(created) / 1000)
                print(f"Created: {dt.strftime('%Y-%m-%d %H:%M')}")

            updated = task.get("date_updated")
            if updated:
                dt = datetime.fromtimestamp(int(updated) / 1000)
                print(f"Updated: {dt.strftime('%Y-%m-%d %H:%M')}")

            due_date = task.get("due_date")
            if due_date:
                dt = datetime.fromtimestamp(int(due_date) / 1000)
                print(f"Due: {dt.strftime('%Y-%m-%d %H:%M')}")

            # Tags
            tags = task.get("tags", [])
            if tags:
                tag_names = [t.get("name", "") for t in tags]
                print(f"Tags: {', '.join(tag_names)}")

            # Custom fields
            custom_fields = task.get("custom_fields", [])
            if custom_fields:
                print()
                print("Custom Fields:")
                for cf in custom_fields:
                    name = cf.get("name", "")
                    value = cf.get("value")
                    if value is not None:
                        print(f"  {name}: {value}")

            # Description
            description = task.get("description")
            if description:
                print()
                print("Description:")
                print("-" * 40)
                print(description)

            # Subtasks
            subtasks = task.get("subtasks", [])
            if subtasks:
                print()
                print(f"Subtasks ({len(subtasks)}):")
                print("-" * 40)
                for st in subtasks:
                    st_status = st.get("status", {}).get("status", "?")
                    print(
                        f"  [{st_status}] {st.get('name', 'Untitled')} ({st.get('id')})"
                    )

            # Comments
            if args.include_comments:
                print()
                print(f"Comments ({len(comments)}):")
                print("-" * 40)
                if not comments:
                    print("  No comments.")
                else:
                    for comment in comments:
                        print()
                        print(format_comment(comment))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
