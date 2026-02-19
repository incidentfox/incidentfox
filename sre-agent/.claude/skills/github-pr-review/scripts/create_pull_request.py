#!/usr/bin/env python3
"""Create a pull request in a GitHub repository.

Usage:
    python create_pull_request.py --repo OWNER/REPO --title "PR title" --head BRANCH_NAME
    python create_pull_request.py --repo OWNER/REPO --title "PR title" --head BRANCH_NAME --base main --body "Description"
    python create_pull_request.py --repo OWNER/REPO --title "PR title" --head BRANCH_NAME --body-file /tmp/pr_body.md
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import create_pull_request


def main():
    parser = argparse.ArgumentParser(
        description="Create a pull request in a GitHub repository"
    )
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--title", required=True, help="Pull request title")
    parser.add_argument(
        "--head", required=True, help="Head branch (source branch with changes)"
    )
    parser.add_argument(
        "--base",
        help="Base branch to merge into (default: repo's default branch)",
    )
    parser.add_argument("--body", default="", help="Pull request description")
    parser.add_argument(
        "--body-file",
        help="Path to file containing PR description (overrides --body)",
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    # Read body from file if provided
    body = args.body
    if args.body_file:
        with open(args.body_file) as f:
            body = f.read()

    result = create_pull_request(
        owner=owner,
        repo=repo,
        title=args.title,
        head=args.head,
        body=body,
        base=args.base,
    )

    print("\nPull request created successfully!")
    print(f"  PR #{result.get('number')}: {result.get('title')}")
    print(f"  URL: {result.get('html_url')}")
    print(f"  State: {result.get('state')}")
    print(f"  Head: {result.get('head', {}).get('ref', 'unknown')}")
    print(f"  Base: {result.get('base', {}).get('ref', 'unknown')}")


if __name__ == "__main__":
    main()
