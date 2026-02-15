#!/usr/bin/env python3
"""Set a feature flag's default variant.

Patches the flagd ConfigMap in Kubernetes, triggering hot-reload.

Usage:
    python set_flag.py <flag_key> <variant> [--dry-run]

Examples:
    python set_flag.py paymentFailure off
    python set_flag.py paymentFailure 50% --dry-run
    python set_flag.py adHighCpu on
    python set_flag.py emailMemoryLeak off
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flagd_client import set_flag_variant


def main():
    parser = argparse.ArgumentParser(description="Set a feature flag's default variant")
    parser.add_argument("flag_key", help="Flag key (e.g., paymentFailure)")
    parser.add_argument("variant", help="Variant to set (e.g., off, on, 50%%)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without applying",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        result = set_flag_variant(args.flag_key, args.variant, dry_run=args.dry_run)
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    prefix = "[DRY RUN] " if result["dry_run"] else ""
    print("=" * 60)
    print(f"{prefix}FLAG UPDATE")
    print("=" * 60)
    print(f"  Flag:      {result['flag']}")
    print(f"  Previous:  {result['old_variant']} (value: {result['old_value']})")
    print(f"  New:       {result['new_variant']} (value: {result['new_value']})")
    if result["dry_run"]:
        print("\n  This is a dry run. No changes were made.")
        print("  Run without --dry-run to apply.")
    else:
        print("\n  ConfigMap updated. flagd will hot-reload within seconds.")
    print("=" * 60)


if __name__ == "__main__":
    main()
