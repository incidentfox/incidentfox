#!/usr/bin/env python3
"""Create a commit status (check) on a GitHub commit.

Usage:
    python create_commit_status.py --repo OWNER/REPO --sha COMMIT_SHA --state success --description "All checks passed"
    python create_commit_status.py --repo OWNER/REPO --sha COMMIT_SHA --state failure --description "Security issues found" --context "IncidentFox/security"
    python create_commit_status.py --repo OWNER/REPO --sha COMMIT_SHA --state pending --description "Review in progress" --target-url "https://example.com/run/123"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import create_commit_status


def main():
    parser = argparse.ArgumentParser(
        description="Create a commit status (check) on a GitHub commit"
    )
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--sha", required=True, help="Commit SHA to set status on")
    parser.add_argument(
        "--state",
        required=True,
        choices=["error", "failure", "pending", "success"],
        help="Status state",
    )
    parser.add_argument(
        "--description", default="", help="Short description (max 140 chars)"
    )
    parser.add_argument(
        "--context",
        default="IncidentFox",
        help="Status context label (default: IncidentFox)",
    )
    parser.add_argument(
        "--target-url",
        help="URL to link from the status (e.g. build/report URL)",
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    result = create_commit_status(
        owner=owner,
        repo=repo,
        sha=args.sha,
        state=args.state,
        description=args.description,
        context=args.context,
        target_url=args.target_url,
    )

    print("\nCommit status created successfully!")
    print(f"  State: {result.get('state')}")
    print(f"  Context: {result.get('context')}")
    print(f"  Description: {result.get('description')}")
    print(f"  URL: {result.get('url')}")
    if result.get("target_url"):
        print(f"  Target URL: {result.get('target_url')}")


if __name__ == "__main__":
    main()
