#!/usr/bin/env python3
"""Search Confluence using CQL (Confluence Query Language).

More powerful than text search - supports filtering by space, type,
labels, dates, etc. Useful for finding runbooks, post-mortems, and
incident documentation.

Common CQL patterns:
- Find runbooks: 'type = page AND label = "runbook"'
- Find post-mortems: 'type = page AND (label = "postmortem" OR title ~ "Post-mortem")'
- Find by space: 'space = "OPS" AND type = page'
- Find recent: 'lastModified >= now("-30d") AND type = page'
- Combined: 'space = "SRE" AND label = "incident" AND lastModified >= now("-90d")'

Usage:
    python search_cql.py --cql "CQL_QUERY" [--limit N]

Examples:
    python search_cql.py --cql 'type = page AND label = "runbook"'
    python search_cql.py --cql 'space = "SRE" AND lastModified >= now("-30d")'
    python search_cql.py --cql 'text ~ "payment" AND label = "postmortem"'
"""

import argparse
import json
import sys

from confluence_client import format_page_result, search_content


def main():
    parser = argparse.ArgumentParser(
        description="Search Confluence using CQL (Confluence Query Language)"
    )
    parser.add_argument(
        "--cql",
        required=True,
        help="CQL query string",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of results (default: 25)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        # Search
        results = search_content(cql=args.cql, limit=args.limit)

        pages = []
        for result in results.get("results", []):
            page = format_page_result(result)
            pages.append(page)

        total_size = results.get("totalSize", len(pages))

        # Output
        if args.json:
            print(
                json.dumps(
                    {
                        "cql": args.cql,
                        "total_results": total_size,
                        "returned_results": len(pages),
                        "pages": pages,
                    },
                    indent=2,
                )
            )
        else:
            print("\n🔍 CQL Search Results")
            print(f"   Query: {args.cql}")
            print(f"   Found: {total_size} total, showing {len(pages)}\n")

            if len(pages) == 0:
                print("   ℹ️  No results found.")
                print()
            else:
                for i, page in enumerate(pages, 1):
                    print(f"{i}. {page['title']}")
                    print(f"   ID: {page['id']}")
                    print(f"   Type: {page.get('type', 'page')}")
                    if page.get("space"):
                        print(f"   Space: {page['space']}")
                    if page.get("url"):
                        print(f"   URL: {page['url']}")
                    if page.get("updated"):
                        print(f"   Last Updated: {page['updated']}")
                    print()

    except Exception as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
