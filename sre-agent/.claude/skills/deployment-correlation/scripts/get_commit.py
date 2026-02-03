#!/usr/bin/env python3
"""Get detailed information about a specific commit.

Usage:
    python get_commit.py --repo owner/repo --sha COMMIT_SHA

Examples:
    python get_commit.py --repo incidentfox/api --sha abc1234
    python get_commit.py --repo incidentfox/api --sha main
"""

import argparse
import json
import sys

from github_client import get_commit, format_commit


def main():
    parser = argparse.ArgumentParser(
        description="Get detailed information about a specific commit"
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository in owner/repo format",
    )
    parser.add_argument(
        "--sha",
        required=True,
        help="Commit SHA (full or abbreviated)",
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

        # Get commit details
        commit = get_commit(owner=owner, repo=repo, sha=args.sha)

        files = commit.get("files", [])
        stats = commit.get("stats", {})

        if args.json:
            output = {
                "repository": args.repo,
                "sha": commit.get("sha"),
                "message": commit.get("commit", {}).get("message", ""),
                "author": {
                    "name": commit.get("commit", {}).get("author", {}).get("name"),
                    "email": commit.get("commit", {}).get("author", {}).get("email"),
                    "date": commit.get("commit", {}).get("author", {}).get("date"),
                },
                "committer": {
                    "name": commit.get("commit", {}).get("committer", {}).get("name"),
                    "date": commit.get("commit", {}).get("committer", {}).get("date"),
                },
                "stats": {
                    "additions": stats.get("additions", 0),
                    "deletions": stats.get("deletions", 0),
                    "total": stats.get("total", 0),
                },
                "files_changed": len(files),
                "files": [
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                        "patch": f.get("patch", "")[:500] if f.get("patch") else None,
                    }
                    for f in files
                ],
                "url": commit.get("html_url"),
            }
            print(json.dumps(output, indent=2))
        else:
            print("=" * 60)
            print("COMMIT DETAILS")
            print("=" * 60)
            print(f"SHA: {commit.get('sha')}")
            print(f"Author: {commit.get('commit', {}).get('author', {}).get('name')}")
            print(f"Date: {commit.get('commit', {}).get('author', {}).get('date')}")
            print(f"URL: {commit.get('html_url')}")
            print()
            print("MESSAGE:")
            print("-" * 40)
            print(commit.get("commit", {}).get("message", ""))
            print()
            print("STATS:")
            print("-" * 40)
            print(f"  Additions: +{stats.get('additions', 0)}")
            print(f"  Deletions: -{stats.get('deletions', 0)}")
            print(f"  Total changes: {stats.get('total', 0)}")
            print()

            if files:
                print(f"FILES CHANGED ({len(files)}):")
                print("-" * 40)
                for f in files:
                    status_icon = {
                        "added": "+",
                        "removed": "-",
                        "modified": "M",
                        "renamed": "R",
                    }.get(f.get("status", ""), "?")
                    additions = f.get("additions", 0)
                    deletions = f.get("deletions", 0)
                    print(f"  [{status_icon}] {f.get('filename')} (+{additions}/-{deletions})")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
