#!/usr/bin/env python3
"""Get files changed in a pull request.

Usage:
    python get_pr_files.py --repo OWNER/REPO --pr NUMBER [--show-patch]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import format_file_changes, format_pr_summary, get_pr, get_pr_files


def main():
    parser = argparse.ArgumentParser(description="Get files changed in a PR")
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument(
        "--show-patch", action="store_true", help="Show diff patch for each file"
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    # Get PR details
    pr = get_pr(owner, repo, args.pr)
    print(format_pr_summary(pr))
    print()

    # Get changed files
    files = get_pr_files(owner, repo, args.pr)
    print(format_file_changes(files))

    if args.show_patch:
        print("\n" + "=" * 70)
        for f in files:
            filename = f.get("filename", "")
            patch = f.get("patch")
            if patch:
                print(f"\n--- {filename} ---")
                print(patch)

    # Also output raw JSON for programmatic use
    print("\n\n--- RAW JSON ---")
    print(json.dumps(files, indent=2))


if __name__ == "__main__":
    main()
