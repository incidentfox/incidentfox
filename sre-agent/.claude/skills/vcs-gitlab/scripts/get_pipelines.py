#!/usr/bin/env python3
"""List CI/CD pipelines for a GitLab project.

Usage:
    python get_pipelines.py --project "group/project" [--status failed]
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="List GitLab pipelines")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument(
        "--status",
        default="",
        help="Filter: running, pending, success, failed, canceled, skipped",
    )
    parser.add_argument("--ref", default="", help="Filter by branch/tag")
    parser.add_argument("--max-results", type=int, default=20, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        params = {"per_page": args.max_results}
        if args.status:
            params["status"] = args.status
        if args.ref:
            params["ref"] = args.ref

        data = gitlab_request(
            "GET", f"projects/{encode_project(args.project)}/pipelines", params=params
        )
        pipelines = [
            {
                "id": p["id"],
                "status": p["status"],
                "ref": p["ref"],
                "sha": p["sha"],
                "web_url": p["web_url"],
                "created_at": p.get("created_at"),
                "source": p.get("source"),
            }
            for p in data
        ]
        result = {"ok": True, "pipelines": pipelines, "count": len(pipelines)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Pipelines ({len(pipelines)} found)")
            for p in pipelines:
                print(
                    f"  [{p['status'].upper():8s}] #{p['id']} | {p['ref']} | {p['sha'][:8]}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
