#!/usr/bin/env python3
"""Get Amplitude chart annotations (deploy markers, release notes, etc.).

Usage:
    python get_chart_annotations.py
    python get_chart_annotations.py --raw
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from amplitude_client import amplitude_request


def main():
    parser = argparse.ArgumentParser(description="Get Amplitude chart annotations")
    parser.add_argument("--raw", action="store_true", help="Output raw JSON response")
    args = parser.parse_args()

    data = amplitude_request("GET", "/annotations")

    if args.raw:
        print(json.dumps(data, indent=2))
        return

    annotations = data.get("data", [])

    print(f"Annotations: {len(annotations)}")
    print("---")

    if not annotations:
        print("No annotations found.")
        return

    for ann in annotations:
        date = ann.get("date", "")
        label = ann.get("label", "")
        details = ann.get("details", "")

        line = f"  [{date}] {label}"
        if details:
            line += f" — {details}"
        print(line)


if __name__ == "__main__":
    main()
