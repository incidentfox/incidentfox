#!/usr/bin/env python3
"""Read a file from a GitHub repository.

Usage:
    python read_file.py --repo OWNER/REPO --path src/app.tsx [--ref main]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_client import read_file


def main():
    parser = argparse.ArgumentParser(description="Read a file from GitHub")
    parser.add_argument("--repo", required=True, help="Repository (OWNER/REPO)")
    parser.add_argument("--path", required=True, help="File path in the repo")
    parser.add_argument(
        "--ref", help="Branch, tag, or commit SHA (default: repo default branch)"
    )
    args = parser.parse_args()

    owner, repo = args.repo.split("/", 1)

    content = read_file(owner, repo, args.path, ref=args.ref)
    print(content)


if __name__ == "__main__":
    main()
