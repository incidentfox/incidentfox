#!/usr/bin/env python3
"""Compare two commits or branches in a GitHub repository.

Usage:
    python compare_commits.py --repo owner/repo --base BASE --head HEAD

Examples:
    python compare_commits.py --repo incidentfox/api --base v1.2.3 --head main
    python compare_commits.py --repo incidentfox/api --base abc123 --head def456
"""

import argparse
import json
import sys

from github_client import compare_commits, format_commit


def main():
    parser = argparse.ArgumentParser(
        description="Compare two commits or branches"
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository in owner/repo format",
    )
    parser.add_argument(
        "--base",
        required=True,
        help="Base commit SHA, branch, or tag",
    )
    parser.add_argument(
        "--head",
        required=True,
        help="Head commit SHA, branch, or tag",
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

        # Compare commits
        comparison = compare_commits(
            owner=owner,
            repo=repo,
            base=args.base,
            head=args.head,
        )

        commits = comparison.get("commits", [])
        files = comparison.get("files", [])
        status = comparison.get("status", "unknown")
        ahead_by = comparison.get("ahead_by", 0)
        behind_by = comparison.get("behind_by", 0)

        if args.json:
            output = {
                "repository": args.repo,
                "base": args.base,
                "head": args.head,
                "status": status,
                "ahead_by": ahead_by,
                "behind_by": behind_by,
                "total_commits": len(commits),
                "files_changed": len(files),
                "commits": [
                    {
                        "sha": c.get("sha"),
                        "message": c.get("commit", {}).get("message", "").split("\n")[0],
                        "author": c.get("commit", {}).get("author", {}).get("name"),
                        "date": c.get("commit", {}).get("author", {}).get("date"),
                    }
                    for c in commits
                ],
                "files": [
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                    }
                    for f in files[:50]  # Limit file list
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print(f"COMPARISON: {args.base}...{args.head}")
            print(f"Repository: {args.repo}")
            print("=" * 60)
            print(f"Status: {status}")
            print(f"Ahead by: {ahead_by} commits")
            print(f"Behind by: {behind_by} commits")
            print(f"Files changed: {len(files)}")
            print()

            if commits:
                print("COMMITS:")
                print("-" * 40)
                for commit in commits[:20]:  # Limit display
                    print(format_commit(commit))
                if len(commits) > 20:
                    print(f"... and {len(commits) - 20} more commits")
                print()

            if files:
                print("FILES CHANGED:")
                print("-" * 40)
                for f in files[:30]:  # Limit display
                    status_icon = {
                        "added": "+",
                        "removed": "-",
                        "modified": "M",
                        "renamed": "R",
                    }.get(f.get("status", ""), "?")
                    additions = f.get("additions", 0)
                    deletions = f.get("deletions", 0)
                    print(f"  [{status_icon}] {f.get('filename')} (+{additions}/-{deletions})")
                if len(files) > 30:
                    print(f"  ... and {len(files) - 30} more files")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
