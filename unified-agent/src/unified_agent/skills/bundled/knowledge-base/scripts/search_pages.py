#!/usr/bin/env python3
"""Search for pages in Confluence.

Usage:
    python search_pages.py --query SEARCH_QUERY [--space SPACE_KEY] [--limit N]

Examples:
    python search_pages.py --query "payment service timeout"
    python search_pages.py --query "database connection" --space SRE
    python search_pages.py --query "api error" --limit 20
"""

import argparse
import json
import sys

from confluence_client import format_page_result, search_content


def main():
    parser = argparse.ArgumentParser(description="Search for pages in Confluence")
    parser.add_argument(
        "--query",
        required=True,
        help="Search query",
    )
    parser.add_argument(
        "--space",
        help="Limit search to a specific space key",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of results (default: 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        # Build CQL query
        cql_parts = [f'text ~ "{args.query}"', "type = page"]
        if args.space:
            cql_parts.append(f'space = "{args.space}"')

        cql = " AND ".join(cql_parts)

        # Search
        results = search_content(cql=cql, limit=args.limit)

        pages = []
        for result in results.get("results", []):
            page = format_page_result(result)
            pages.append(page)

        # Output
        if args.json:
            print(
                json.dumps(
                    {"query": args.query, "total": len(pages), "pages": pages}, indent=2
                )
            )
        else:
            print(f"\n🔍 Found {len(pages)} page(s) for query: {args.query}\n")
            if args.space:
                print(f"   Space: {args.space}\n")

            for i, page in enumerate(pages, 1):
                print(f"{i}. {page['title']}")
                print(f"   ID: {page['id']}")
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
