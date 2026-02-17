#!/usr/bin/env python3
"""Get jobs for a specific GitLab pipeline.

Usage:
    python get_pipeline_jobs.py --project "group/project" --pipeline-id 12345
"""

import argparse
import json
import sys

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Get pipeline jobs")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--pipeline-id", required=True, type=int, help="Pipeline ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        proj = encode_project(args.project)
        data = gitlab_request(
            "GET",
            f"projects/{proj}/pipelines/{args.pipeline_id}/jobs",
            params={"per_page": 100},
        )

        jobs = [
            {
                "id": j["id"],
                "name": j["name"],
                "stage": j["stage"],
                "status": j["status"],
                "web_url": j["web_url"],
                "duration": j.get("duration"),
                "failure_reason": j.get("failure_reason"),
            }
            for j in data
        ]
        result = {
            "ok": True,
            "pipeline_id": args.pipeline_id,
            "jobs": jobs,
            "count": len(jobs),
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Pipeline #{args.pipeline_id} Jobs ({len(jobs)})")
            for job in jobs:
                duration = f"{job['duration']:.0f}s" if job.get("duration") else "?"
                print(
                    f"  [{job['status'].upper():8s}] {job['stage']:15s} -> {job['name']} ({duration})"
                )
                if job.get("failure_reason"):
                    print(f"    Failure: {job['failure_reason']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
