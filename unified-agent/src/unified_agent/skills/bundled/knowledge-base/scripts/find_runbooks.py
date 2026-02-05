#!/usr/bin/env python3
"""Find runbooks in Confluence for a service or alert.

Usage:
    python find_runbooks.py [--service SERVICE] [--alert ALERT_NAME] [--space SPACE_KEY] [--limit N]

Examples:
    python find_runbooks.py --service payment
    python find_runbooks.py --alert "HighErrorRate"
    python find_runbooks.py --service checkout --space OPS
"""

import argparse
import json
import sys

from confluence_client import format_page_result, search_content


def main():
    parser = argparse.ArgumentParser(
        description="Find runbooks in Confluence for a service or alert"
    )
    parser.add_argument(
        "--service",
        help="Service name to search for",
    )
    parser.add_argument(
        "--alert",
        help="Alert name to search for",
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

    if not args.service and not args.alert:
        print("❌ Error: Must provide --service or --alert", file=sys.stderr)
        sys.exit(1)

    try:
        # Build CQL query
        # Look for runbook labels/titles
        runbook_filter = '(label = "runbook" OR label = "playbook" OR label = "sop" OR title ~ "runbook" OR title ~ "playbook")'

        cql_parts = [runbook_filter, "type = page"]

        # Add service/alert search terms
        search_terms = []
        if args.service:
            search_terms.append(
                f'(title ~ "{args.service}" OR text ~ "{args.service}")'
            )
        if args.alert:
            search_terms.append(f'(title ~ "{args.alert}" OR text ~ "{args.alert}")')

        if search_terms:
            cql_parts.append(f"({' OR '.join(search_terms)})")

        if args.space:
            cql_parts.append(f'space = "{args.space}"')

        cql = " AND ".join(cql_parts)

        # Search
        results = search_content(cql=cql, limit=args.limit)

        runbooks = []
        for result in results.get("results", []):
            page = format_page_result(result)
            # Add relevance score
            page["relevance"] = (
                "high"
                if args.service and args.service.lower() in page["title"].lower()
                else "medium"
            )
            runbooks.append(page)

        # Output
        if args.json:
            print(
                json.dumps(
                    {
                        "service": args.service,
                        "alert": args.alert,
                        "total": len(runbooks),
                        "has_runbook": len(runbooks) > 0,
                        "runbooks": runbooks,
                    },
                    indent=2,
                )
            )
        else:
            search_desc = []
            if args.service:
                search_desc.append(f"service: {args.service}")
            if args.alert:
                search_desc.append(f"alert: {args.alert}")

            print(
                f"\n📚 Found {len(runbooks)} runbook(s) for {', '.join(search_desc)}\n"
            )
            if args.space:
                print(f"   Space: {args.space}\n")

            if len(runbooks) == 0:
                print(
                    "   ℹ️  No runbooks found. Consider searching for general documentation."
                )
                print()
            else:
                for i, runbook in enumerate(runbooks, 1):
                    relevance_emoji = "🎯" if runbook["relevance"] == "high" else "📄"
                    print(f"{i}. {relevance_emoji} {runbook['title']}")
                    print(f"   ID: {runbook['id']}")
                    if runbook.get("space"):
                        print(f"   Space: {runbook['space']}")
                    if runbook.get("url"):
                        print(f"   URL: {runbook['url']}")
                    if runbook.get("updated"):
                        print(f"   Last Updated: {runbook['updated']}")
                    print()

    except Exception as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
