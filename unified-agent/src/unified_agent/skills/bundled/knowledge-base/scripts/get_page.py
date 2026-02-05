#!/usr/bin/env python3
"""Get the full content of a Confluence page.

Usage:
    python get_page.py --page-id PAGE_ID
    python get_page.py --title "Page Title" --space SPACE_KEY

Examples:
    python get_page.py --page-id 123456789
    python get_page.py --title "Payment Service Runbook" --space SRE
"""

import argparse
import json
import re
import sys

from confluence_client import get_page_by_id, get_page_by_title


def html_to_text(html: str) -> str:
    """Convert Confluence storage format HTML to plain text.

    Handles Confluence macros and CDATA sections.
    """
    # Extract CDATA content (Confluence macros often use CDATA)
    cdata_pattern = r"<!\[CDATA\[(.*?)\]\]>"
    cdata_matches = re.findall(cdata_pattern, html, re.DOTALL)

    # If we found CDATA content, use that (it's usually markdown or plain text)
    if cdata_matches:
        return "\n\n".join(cdata_matches)

    # Otherwise, strip HTML tags
    text = re.sub(r"<[^>]+>", "", html)
    # Clean up multiple newlines
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Get the full content of a Confluence page"
    )
    parser.add_argument(
        "--page-id",
        help="Page ID",
    )
    parser.add_argument(
        "--title",
        help="Page title (requires --space)",
    )
    parser.add_argument(
        "--space",
        help="Space key (required with --title)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--raw-html",
        action="store_true",
        help="Show raw HTML content instead of plain text",
    )
    args = parser.parse_args()

    if not args.page_id and not (args.title and args.space):
        print(
            "❌ Error: Must provide --page-id or (--title and --space)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        # Get page
        if args.page_id:
            page = get_page_by_id(args.page_id)
        else:
            # Get by title and space
            page = get_page_by_title(space=args.space, title=args.title)

        # Extract content
        body = page.get("body", {})
        storage = body.get("storage", {})
        html_content = storage.get("value", "")

        # Convert to text unless raw HTML requested
        if args.raw_html:
            content = html_content
        else:
            content = html_to_text(html_content)

        # Construct page URL from environment or page data
        import os

        base_url = os.getenv("CONFLUENCE_BASE_URL") or os.getenv("CONFLUENCE_URL", "")
        base_url = base_url.rstrip("/")
        if base_url.endswith("/wiki"):
            base_url = base_url[:-5]
        webui = page.get("_links", {}).get("webui", "")
        page_url = f"{base_url}/wiki{webui}" if base_url and webui else ""

        # Output
        if args.json:
            output = {
                "id": page.get("id"),
                "title": page.get("title"),
                "space": page.get("space", {}).get("key"),
                "content": content,
                "url": page_url,
                "version": page.get("version", {}).get("number"),
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"\n📄 {page.get('title')}")
            print(f"   ID: {page.get('id')}")
            if page.get("space", {}).get("key"):
                print(f"   Space: {page.get('space', {}).get('key')}")
            if page_url:
                print(f"   URL: {page_url}")
            if page.get("version", {}).get("number"):
                print(f"   Version: {page.get('version', {}).get('number')}")
            print("\n" + "=" * 80)
            print(content)
            print("=" * 80 + "\n")

    except Exception as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
