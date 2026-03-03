#!/usr/bin/env python3
"""List files and directories in a GitLab repository.

Usage:
    python get_repository_tree.py --project "group/project" [--path "src/"] [--ref main]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List repository tree")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--path", default="", help="Path inside repository")
    parser.add_argument("--ref", default="", help="Branch, tag, or commit SHA")
    parser.add_argument(
        "--recursive", action="store_true", help="List files recursively"
    )
    parser.add_argument("--max-results", type=int, default=100, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"per_page": args.max_results}
        if args.path:
            params["path"] = args.path
        if args.ref:
            params["ref"] = args.ref
        if args.recursive:
            params["recursive"] = "true"

        data = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/repository/tree",
            params=params,
        )
        entries = [
            {
                "name": e["name"],
                "type": e["type"],  # "tree" (dir) or "blob" (file)
                "path": e["path"],
                "mode": e.get("mode"),
            }
            for e in data
        ]
        result = {"ok": True, "entries": entries, "count": len(entries)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            path_label = args.path or "/"
            print(f"Repository tree: {path_label} ({len(entries)} entries)")
            for e in entries:
                icon = "dir " if e["type"] == "tree" else "file"
                print(f"  [{icon}] {e['path']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
