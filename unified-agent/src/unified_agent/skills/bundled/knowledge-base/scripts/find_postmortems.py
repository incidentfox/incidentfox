#!/usr/bin/env python3
"""Find post-mortem documents in Confluence.

Usage:
    python find_postmortems.py [--service SERVICE] [--days N] [--space SPACE_KEY] [--limit N]

Examples:
    python find_postmortems.py --service payment
    python find_postmortems.py --service payment --days 180
    python find_postmortems.py --space SRE
"""

import argparse
import json
import sys

from confluence_client import format_page_result, search_content


def main():
    parser = argparse.ArgumentParser(
        description="Find post-mortem documents in Confluence"
    )
    parser.add_argument(
        "--service",
        help="Service name to filter by",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Look back this many days (default: 90)",
    )
    parser.add_argument(
        "--space",
        help="Limit search to a specific space key",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results (default: 20)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        # Build CQL query
        cql_parts = [
            f'lastModified >= now("-{args.days}d")',
            "type = page",
            '(label = "postmortem" OR label = "post-mortem" OR label = "incident-review" OR title ~ "Post-mortem" OR title ~ "Postmortem" OR title ~ "Incident Review")',
        ]

        if args.service:
            cql_parts.append(f'(title ~ "{args.service}" OR text ~ "{args.service}")')

        if args.space:
            cql_parts.append(f'space = "{args.space}"')

        cql = " AND ".join(cql_parts)

        # Search
        results = search_content(cql=cql, limit=args.limit)

        postmortems = []
        for result in results.get("results", []):
            page = format_page_result(result)
            postmortems.append(page)

        # Output
        if args.json:
            print(
                json.dumps(
                    {
                        "service": args.service,
                        "days": args.days,
                        "total": len(postmortems),
                        "postmortems": postmortems,
                    },
                    indent=2,
                )
            )
        else:
            print(f"\n📋 Found {len(postmortems)} post-mortem(s)")
            if args.service:
                print(f"   Service: {args.service}")
            print(f"   Last {args.days} days")
            if args.space:
                print(f"   Space: {args.space}")
            print()

            if len(postmortems) == 0:
                print("   ℹ️  No post-mortems found in the specified time range.")
                print()
            else:
                for i, pm in enumerate(postmortems, 1):
                    print(f"{i}. {pm['title']}")
                    print(f"   ID: {pm['id']}")
                    if pm.get("space"):
                        print(f"   Space: {pm['space']}")
                    if pm.get("url"):
                        print(f"   URL: {pm['url']}")
                    if pm.get("updated"):
                        print(f"   Last Updated: {pm['updated']}")
                    print()

    except Exception as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
