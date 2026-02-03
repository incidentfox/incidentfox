#!/usr/bin/env python3
"""List recent commits from a GitHub repository.

Usage:
    python list_commits.py --repo owner/repo [--branch BRANCH] [--since TIMESTAMP] [--limit N]

Examples:
    python list_commits.py --repo incidentfox/api --branch main --limit 20
    python list_commits.py --repo incidentfox/api --since "2026-01-27T00:00:00Z"
"""

import argparse
import json
import sys

from github_client import format_commit, list_commits


def main():
    parser = argparse.ArgumentParser(
        description="List recent commits from a GitHub repository"
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository in owner/repo format",
    )
    parser.add_argument(
        "--branch",
        help="Branch name (default: default branch)",
    )
    parser.add_argument(
        "--since",
        help="Only commits after this ISO 8601 timestamp",
    )
    parser.add_argument(
        "--until",
        help="Only commits before this ISO 8601 timestamp",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum commits to return (default: 20)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        # Parse owner/repo
        if "/" not in args.repo:
            print("Error: --repo must be in owner/repo format", file=sys.stderr)
            sys.exit(1)
        owner, repo = args.repo.split("/", 1)

        # Fetch commits
        commits = list_commits(
            owner=owner,
            repo=repo,
            branch=args.branch,
            since=args.since,
            until=args.until,
            per_page=args.limit,
        )

        if args.json:
            output = {
                "repository": args.repo,
                "branch": args.branch or "default",
                "count": len(commits),
                "commits": [
                    {
                        "sha": c.get("sha"),
                        "message": c.get("commit", {})
                        .get("message", "")
                        .split("\n")[0],
                        "author": c.get("commit", {}).get("author", {}).get("name"),
                        "date": c.get("commit", {}).get("author", {}).get("date"),
                        "url": c.get("html_url"),
                    }
                    for c in commits
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print(f"RECENT COMMITS: {args.repo}")
            if args.branch:
                print(f"Branch: {args.branch}")
            print("=" * 60)
            print(f"Found: {len(commits)} commits")
            print()

            if not commits:
                print("No commits found matching criteria.")
            else:
                for commit in commits:
                    print(format_commit(commit))
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
