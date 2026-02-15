#!/usr/bin/env python3
"""Search code in a GitHub repository.

Usage:
    python search_code.py --query "trackEvent" --repo OWNER/REPO
    python search_code.py --query "amplitude" --repo OWNER/REPO
    python search_code.py --query "analytics.track" --repo OWNER/REPO
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import search_code


def main():
    parser = argparse.ArgumentParser(description="Search code in a GitHub repo")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--repo", help="Limit to specific repo (OWNER/REPO)")
    parser.add_argument("--limit", type=int, default=20, help="Max results")
    args = parser.parse_args()

    result = search_code(args.query, repo=args.repo, per_page=args.limit)

    total = result.get("total_count", 0)
    items = result.get("items", [])

    print(f"Found {total} results (showing {len(items)}):\n")

    for item in items:
        repo_name = item.get("repository", {}).get("full_name", "")
        file_path = item.get("path", "")
        url = item.get("html_url", "")
        print(f"  {repo_name}/{file_path}")
        print(f"    {url}")

    # Raw JSON for programmatic use
    print("\n\n--- RAW JSON ---")
    print(json.dumps(items, indent=2))


if __name__ == "__main__":
    main()
