#!/usr/bin/env python3
"""Get a specific feature flag's configuration and current value.

Usage:
    python get_flag.py <flag_key>
    python get_flag.py paymentFailure --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flagd_client import get_flag


def main():
    parser = argparse.ArgumentParser(description="Get a feature flag's value")
    parser.add_argument("flag_key", help="Flag key (e.g., paymentFailure)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        flag = get_flag(args.flag_key)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if flag is None:
        print(f"Flag '{args.flag_key}' not found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps({args.flag_key: flag}, indent=2))
        return

    default = flag.get("defaultVariant", "unknown")
    variants = flag.get("variants", {})
    current_value = variants.get(default, "?")
    state = flag.get("state", "ENABLED")

    print("=" * 50)
    print(f"FLAG: {args.flag_key}")
    print("=" * 50)
    print(f"  Current variant: {default}")
    print(f"  Current value:   {current_value}")
    print(f"  State:           {state}")
    print("\n  Available variants:")
    for name, value in variants.items():
        marker = " <-- current" if name == default else ""
        print(f"    {name}: {value}{marker}")
    print("=" * 50)


if __name__ == "__main__":
    main()
