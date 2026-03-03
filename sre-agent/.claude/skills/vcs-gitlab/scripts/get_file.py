#!/usr/bin/env python3
"""Read file contents from a GitLab repository.

Usage:
    python get_file.py --project "group/project" --path "src/main.py" [--ref main]
"""

import argparse
import base64
import json
import sys
import urllib.parse

from gitlab_client import encode_project, gitlab_request


def main():
    parser = argparse.ArgumentParser(description="Get file from repository")
    parser.add_argument("--project", required=True, help="Project ID or path")
    parser.add_argument("--path", required=True, help="File path in repository")
    parser.add_argument("--ref", default="", help="Branch, tag, or commit SHA")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        encoded_path = urllib.parse.quote(args.path, safe="")
        params = {}
        if args.ref:
            params["ref"] = args.ref

        data = gitlab_request(
            "GET",
            f"projects/{encode_project(args.project)}/repository/files/{encoded_path}",
            params=params,
        )

        content = ""
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode(
                "utf-8", errors="replace"
            )
        else:
            content = data.get("content", "")

        result = {
            "ok": True,
            "file_name": data.get("file_name"),
            "file_path": data.get("file_path"),
            "size": data.get("size"),
            "ref": data.get("ref"),
            "last_commit_id": data.get("last_commit_id"),
            "content": content,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"File: {result['file_path']} ({result.get('size', '?')} bytes)")
            print(
                f"Ref: {result.get('ref', '?')} | Last commit: {result.get('last_commit_id', '?')[:12]}"
            )
            print("---")
            print(content)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
