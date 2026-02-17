#!/usr/bin/env python3
"""List contents of a Google Drive folder."""

import argparse
import json
import sys

from google_client import _is_proxy_mode, drive_request, get_drive_service


def main():
    parser = argparse.ArgumentParser(description="List Drive folder")
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        q = f"'{args.folder_id}' in parents"
        if _is_proxy_mode():
            data = drive_request(
                "GET",
                "/files",
                params={"q": q, "fields": "files(id,name,mimeType,webViewLink)"},
            )
        else:
            service = get_drive_service(readonly=True)
            data = (
                service.files()
                .list(q=q, fields="files(id,name,mimeType,webViewLink)")
                .execute()
            )

        files = [
            {
                "id": f["id"],
                "name": f["name"],
                "type": f["mimeType"],
                "url": f.get("webViewLink"),
            }
            for f in data.get("files", [])
        ]

        if args.json:
            print(json.dumps(files, indent=2))
        else:
            print(f"Folder contents: {len(files)} items")
            for f in files:
                print(f"  {f['name']} ({f['type'][:30]})")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
