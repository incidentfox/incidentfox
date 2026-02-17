#!/usr/bin/env python3
"""Get file changes (diff) for a merge request.

Usage:
    python get_mr_changes.py --project "group/project" --mr-iid 42
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Get MR file changes")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--mr-iid", required=True, type=int, help="MR IID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/merge_requests/{args.mr_iid}/changes",
        )

        changes = [
            {
                "old_path": c.get("old_path"),
                "new_path": c.get("new_path"),
                "new_file": c.get("new_file"),
                "deleted_file": c.get("deleted_file"),
                "renamed_file": c.get("renamed_file"),
                "diff": c.get("diff", "")[:2000],
            }
            for c in data.get("changes", [])
        ]
        result = {
            "ok": True,
            "mr_iid": args.mr_iid,
            "changes": changes,
            "count": len(changes),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"MR !{args.mr_iid} Changes ({len(changes)} files)")
            for c in changes:
                action = (
                    "ADD"
                    if c.get("new_file")
                    else (
                        "DEL"
                        if c.get("deleted_file")
                        else "REN" if c.get("renamed_file") else "MOD"
                    )
                )
                print(f"  [{action}] {c.get('new_path', c.get('old_path', '?'))}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
