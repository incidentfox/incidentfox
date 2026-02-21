#!/usr/bin/env python3
"""Create or update a file in a GitHub repository.

Usage:
    python create_or_update_file.py --repo OWNER/REPO --path FILE_PATH --branch BRANCH --message "commit msg" --file /tmp/content.txt
    python create_or_update_file.py --repo OWNER/REPO --path FILE_PATH --branch BRANCH --message "commit msg" --sha CURRENT_SHA --file /tmp/content.txt
    echo "file content" | python create_or_update_file.py --repo OWNER/REPO --path FILE_PATH --branch BRANCH --message "commit msg"

For updates, pass --sha with the current file SHA (get it from read_file.py or the read_file_with_sha client function).
Content is read from --file or stdin if --file is not provided.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import create_or_update_file


def main():
    parser = argparse.ArgumentParser(
        description="Create or update a file in a GitHub repository"
    )
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--path", required=True, help="File path in the repository")
    parser.add_argument("--branch", required=True, help="Branch to commit to")
    parser.add_argument("--message", required=True, help="Commit message")
    parser.add_argument(
        "--sha",
        help="Current file SHA (required for updates, get from read_file_with_sha)",
    )
    parser.add_argument(
        "--file",
        help="Path to local file containing the content (reads from stdin if not provided)",
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    # Read content from file or stdin
    if args.file:
        with open(args.file) as f:
            content = f.read()
    else:
        content = sys.stdin.read()

    if not content:
        print(
            "Error: No content provided. Use --file or pipe content to stdin.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = create_or_update_file(
        owner=owner,
        repo=repo,
        path=args.path,
        content=content,
        message=args.message,
        branch=args.branch,
        sha=args.sha,
    )

    content_info = result.get("content", {})
    commit_info = result.get("commit", {})
    print("\nFile committed successfully!")
    print(f"  Path: {content_info.get('path', args.path)}")
    print(f"  SHA: {content_info.get('sha', 'unknown')}")
    print(f"  Commit: {commit_info.get('sha', 'unknown')[:12]}")
    print(f"  Message: {commit_info.get('message', args.message)}")


if __name__ == "__main__":
    main()
