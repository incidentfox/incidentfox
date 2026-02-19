#!/usr/bin/env python3
"""Create a new branch in a GitHub repository.

Usage:
    python create_branch.py --repo OWNER/REPO --branch BRANCH_NAME
    python create_branch.py --repo OWNER/REPO --branch BRANCH_NAME --from-branch develop
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import create_branch


def main():
    parser = argparse.ArgumentParser(
        description="Create a new branch in a GitHub repository"
    )
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--branch", required=True, help="Name of the new branch")
    parser.add_argument(
        "--from-branch",
        help="Source branch to create from (default: repo's default branch)",
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    result = create_branch(
        owner=owner,
        repo=repo,
        branch=args.branch,
        from_branch=args.from_branch,
    )

    print("\nBranch created successfully!")
    print(f"  Ref: {result.get('ref')}")
    print(f"  SHA: {result.get('object', {}).get('sha', 'unknown')}")


if __name__ == "__main__":
    main()
