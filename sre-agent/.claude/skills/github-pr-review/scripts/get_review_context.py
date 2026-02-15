#!/usr/bin/env python3
"""Get existing review context for a PR.

Shows prior reviews and inline comments so the agent can avoid
duplicating work and focus on new/changed code.

Usage:
    python get_review_context.py --repo OWNER/REPO --pr NUMBER [--bot-marker "Telemetry Review"]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import (
    compare_commits,
    get_pr,
    list_review_comments,
    list_reviews,
)


def main():
    parser = argparse.ArgumentParser(
        description="Get existing review context for incremental reviews"
    )
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument(
        "--bot-marker",
        default="Telemetry Review",
        help="Text marker to identify bot's own reviews (default: 'Telemetry Review')",
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    # Get PR details
    pr = get_pr(owner, repo, args.pr)
    head_sha = pr.get("head", {}).get("sha", "")

    # Get all reviews
    reviews = list_reviews(owner, repo, args.pr)

    # Find our previous reviews (by marker in body)
    our_reviews = [r for r in reviews if args.bot_marker in (r.get("body") or "")]

    # Get all inline comments
    inline_comments = list_review_comments(owner, repo, args.pr)

    # Find our inline comments (comments belonging to our reviews)
    our_review_ids = {r["id"] for r in our_reviews}
    our_comments = [
        c for c in inline_comments if c.get("pull_request_review_id") in our_review_ids
    ]

    # Find the most recent review commit
    last_reviewed_sha = None
    if our_reviews:
        # Reviews are returned chronologically; take the last one
        last_review = our_reviews[-1]
        last_reviewed_sha = last_review.get("commit_id")

    print(f"PR #{args.pr}: {pr.get('title', '')}")
    print(f"Current HEAD: {head_sha[:12]}")
    print(f"Previous bot reviews: {len(our_reviews)}")
    print(f"Previous bot inline comments: {len(our_comments)}")

    if last_reviewed_sha:
        print(f"Last reviewed commit: {last_reviewed_sha[:12]}")

        if last_reviewed_sha == head_sha:
            print(
                "\nStatus: ALREADY REVIEWED at current HEAD — no new changes to review."
            )
            print("ACTION: Skip this PR.")
        else:
            print("\nNew commits since last review:")
            try:
                comparison = compare_commits(owner, repo, last_reviewed_sha, head_sha)
                new_files = comparison.get("files", [])
                total_commits = comparison.get("total_commits", 0)
                print(f"  Commits: {total_commits}")
                print(f"  Files changed: {len(new_files)}")
                for f in new_files:
                    print(
                        f"    [{f.get('status')}] {f.get('filename')} "
                        f"(+{f.get('additions', 0)} -{f.get('deletions', 0)})"
                    )
                print("\nACTION: Review ONLY the new/changed files listed above.")
            except Exception as e:
                print(f"  Could not compare commits: {e}")
                print("ACTION: Review the full PR diff.")
    else:
        print("\nStatus: FIRST REVIEW — no prior bot reviews found.")
        print("ACTION: Review the full PR diff.")

    # Print existing comments for context
    if our_comments:
        print(f"\n--- Previous inline comments ({len(our_comments)}) ---")
        for c in our_comments:
            path = c.get("path", "")
            line = c.get("original_line") or c.get("line") or c.get("position")
            body_preview = (c.get("body") or "")[:120]
            print(f"  {path}:{line} — {body_preview}")

    # Print other people's comments for awareness
    other_comments = [
        c
        for c in inline_comments
        if c.get("pull_request_review_id") not in our_review_ids
    ]
    if other_comments:
        print(f"\n--- Other reviewer comments ({len(other_comments)}) ---")
        for c in other_comments:
            user = c.get("user", {}).get("login", "")
            path = c.get("path", "")
            body_preview = (c.get("body") or "")[:120]
            print(f"  @{user} on {path}: {body_preview}")


if __name__ == "__main__":
    main()
