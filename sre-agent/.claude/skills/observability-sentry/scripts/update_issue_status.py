#!/usr/bin/env python3
"""Update the status of a Sentry issue.

Usage:
    python update_issue_status.py --issue-id 12345678 --status resolved
"""

import argparse
import json
import sys

from sentry_client import sentry_request


def main():
    parser = argparse.ArgumentParser(description="Update Sentry issue status")
    parser.add_argument("--issue-id", required=True, help="Sentry issue ID")
    parser.add_argument(
        "--status",
        required=True,
        choices=["resolved", "unresolved", "ignored", "resolvedInNextRelease"],
        help="New status",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        sentry_request(
            "PUT", f"issues/{args.issue_id}/", json_body={"status": args.status}
        )
        result = {"ok": True, "issue_id": args.issue_id, "status": args.status}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Issue {args.issue_id} status updated to: {args.status}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
