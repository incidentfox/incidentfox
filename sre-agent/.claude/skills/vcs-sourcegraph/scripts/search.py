#!/usr/bin/env python3
"""Search code across repositories in Sourcegraph."""

import argparse
import json
import sys

from sourcegraph_client import graphql_request


def main():
    parser = argparse.ArgumentParser(description="Search Sourcegraph")
    parser.add_argument("--query", required=True)
    parser.add_argument("--repo-filter", help="Repo filter (e.g. github.com/org/*)")
    parser.add_argument("--file-filter", help="File filter (e.g. *.py)")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        search_query = args.query
        if args.repo_filter:
            search_query += f" repo:{args.repo_filter}"
        if args.file_filter:
            search_query += f" file:{args.file_filter}"

        gql = """query Search($query: String!) { search(query: $query) { results { results { ... on FileMatch { file { path url repository { name } } lineMatches { lineNumber line } } } } } }"""
        data = graphql_request(gql, {"query": search_query})

        matches = []
        for result in data.get("search", {}).get("results", {}).get("results", []):
            if len(matches) >= args.limit:
                break
            if "file" not in result:
                continue
            matches.append(
                {
                    "file_path": result["file"]["path"],
                    "repository": result["file"]["repository"]["name"],
                    "url": result["file"]["url"],
                    "matches": [
                        {"line": m["lineNumber"], "content": m["line"]}
                        for m in result.get("lineMatches", [])[:3]
                    ],
                }
            )

        if args.json:
            print(json.dumps(matches, indent=2))
        else:
            print(f"Found: {len(matches)} file matches")
            current_repo = None
            for m in matches:
                if m["repository"] != current_repo:
                    current_repo = m["repository"]
                    print(f"\n  {current_repo}/")
                print(f"    {m['file_path']}")
                for match in m["matches"]:
                    print(f"      L{match['line']}: {match['content'][:100]}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
