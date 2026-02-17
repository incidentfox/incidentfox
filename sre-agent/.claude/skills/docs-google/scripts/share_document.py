#!/usr/bin/env python3
"""Share a Google Doc."""

import argparse
import json
import sys

from google_client import _is_proxy_mode, drive_request, get_drive_service


def main():
    parser = argparse.ArgumentParser(description="Share Google Doc")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--email", help="Email to share with")
    parser.add_argument("--role", default="reader", help="reader, writer, or commenter")
    parser.add_argument(
        "--anyone", action="store_true", help="Share with anyone with link"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.email and not args.anyone:
        print("Error: Provide --email or --anyone", file=sys.stderr)
        sys.exit(1)

    try:
        if args.anyone:
            perm = {"type": "anyone", "role": args.role}
        else:
            perm = {"type": "user", "role": args.role, "emailAddress": args.email}

        if _is_proxy_mode():
            drive_request(
                "POST", f"/files/{args.document_id}/permissions", json_body=perm
            )
        else:
            service = get_drive_service()
            service.permissions().create(
                fileId=args.document_id, body=perm, fields="id"
            ).execute()

        shared_with = "anyone" if args.anyone else args.email
        result = {
            "document_id": args.document_id,
            "shared_with": shared_with,
            "role": args.role,
            "success": True,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Shared {args.document_id} with {shared_with} as {args.role}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
