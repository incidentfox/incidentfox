#!/usr/bin/env python3
"""Get details of a Vercel project.

Usage:
    python get_project.py --project PROJECT_ID_OR_NAME [--json]

Examples:
    python get_project.py --project my-webapp
    python get_project.py --project prj_abc123 --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vercel_client import format_project, get_project


def main():
    parser = argparse.ArgumentParser(description="Get Vercel project details")
    parser.add_argument("--project", required=True, help="Project ID or name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        project = get_project(args.project)

        if args.json:
            result = {
                "ok": True,
                "project": project,
            }
            print(json.dumps(result, indent=2))
        else:
            print(format_project(project))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
