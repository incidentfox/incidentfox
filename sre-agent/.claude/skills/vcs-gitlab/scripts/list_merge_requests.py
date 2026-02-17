#!/usr/bin/env python3
"""List merge requests for a GitLab project.

Usage:
    python list_merge_requests.py --project "group/project" [--state opened]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List merge requests")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument(
        "--state", default="opened", help="State: opened, closed, merged, all"
    )
    parser.add_argument("--max-results", type=int, default=20, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"state": args.state, "per_page": args.max_results}
        data = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/merge_requests",
            params=params,
        )

        mrs = [
            {
                "iid": mr["iid"],
                "title": mr["title"],
                "state": mr["state"],
                "source_branch": mr["source_branch"],
                "target_branch": mr["target_branch"],
                "author": (
                    mr.get("author", {}).get("name") if mr.get("author") else None
                ),
                "web_url": mr["web_url"],
                "merged_at": mr.get("merged_at"),
                "labels": mr.get("labels", []),
            }
            for mr in data
        ]
        result = {"ok": True, "merge_requests": mrs, "count": len(mrs)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Merge Requests ({len(mrs)} {args.state})")
            for mr in mrs:
                print(f"  !{mr['iid']} [{mr['state']}] {mr['title']}")
                print(f"    {mr['source_branch']} -> {mr['target_branch']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
