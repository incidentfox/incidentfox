#!/usr/bin/env python3
"""List Vercel projects.

Usage:
    python list_projects.py [--limit 20] [--json]

Examples:
    python list_projects.py
    python list_projects.py --limit 50
    python list_projects.py --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vercel_client import format_project, list_projects


def main():
    parser = argparse.ArgumentParser(description="List Vercel projects")
    parser.add_argument(
        "--limit", type=int, default=20, help="Max projects to return (default: 20)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        projects = list_projects(limit=args.limit)

        if args.json:
            result = {
                "ok": True,
                "projects": projects,
                "count": len(projects),
            }
            print(json.dumps(result, indent=2))
        else:
            print(f"Vercel Projects: {len(projects)}\n")
            for p in projects:
                print(format_project(p))
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
