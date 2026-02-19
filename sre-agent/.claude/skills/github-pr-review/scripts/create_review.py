#!/usr/bin/env python3
"""Create a PR review with inline comments.

Usage:
    python create_review.py --repo OWNER/REPO --pr NUMBER --body "Summary" --comments-file /tmp/comments.json
    python create_review.py --repo OWNER/REPO --pr NUMBER --body "LGTM" --event APPROVE

The --comments-file should be a JSON file containing an array of objects:
[
  {
    "path": "src/components/Checkout.tsx",
    "line": 42,
    "body": "Consider adding a telemetry event here:\\n```suggestion\\ntrackEvent('checkout_started', { itemCount: items.length });\\n```"
  }
]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import create_review


def main():
    parser = argparse.ArgumentParser(
        description="Create a PR review with inline comments"
    )
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--body", required=True, help="Review summary body")
    parser.add_argument(
        "--comments-file",
        help="Path to JSON file with inline comments [{path, line, body}]",
    )
    parser.add_argument(
        "--event",
        default="COMMENT",
        choices=["COMMENT", "APPROVE", "REQUEST_CHANGES"],
        help="Review event type (default: COMMENT)",
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    # Load inline comments if provided
    comments = None
    if args.comments_file:
        with open(args.comments_file) as f:
            comments = json.load(f)
        print(f"Loaded {len(comments)} inline comments from {args.comments_file}")

    # Create the review
    result = create_review(
        owner=owner,
        repo=repo,
        pr_number=args.pr,
        body=args.body,
        comments=comments,
        event=args.event,
    )

    print("\nReview created successfully!")
    print(f"  Review ID: {result.get('id')}")
    print(f"  State: {result.get('state')}")
    print(f"  URL: {result.get('html_url')}")
    if comments:
        print(f"  Inline comments: {len(comments)}")


if __name__ == "__main__":
    main()
