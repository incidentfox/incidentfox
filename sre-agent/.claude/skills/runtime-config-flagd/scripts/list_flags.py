#!/usr/bin/env python3
"""List all feature flags and their current configuration.

Usage:
    python list_flags.py [--verbose]
    python list_flags.py --incidents-only
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flagd_client import get_all_flags

# Flags that correspond to incident scenarios
INCIDENT_FLAGS = {
    "adHighCpu",
    "adManualGc",
    "adFailure",
    "emailMemoryLeak",
    "paymentFailure",
    "paymentUnreachable",
    "cartFailure",
    "imageSlowLoad",
    "kafkaQueueProblems",
    "loadGeneratorFloodHomepage",
    "recommendationCacheFailure",
    "productCatalogFailure",
    "llmInaccurateResponse",
    "llmRateLimitError",
}


def main():
    parser = argparse.ArgumentParser(description="List all feature flags")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full variant details",
    )
    parser.add_argument(
        "--incidents-only",
        action="store_true",
        help="Only show incident-related flags",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        flags = get_all_flags()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.incidents_only:
        flags = {k: v for k, v in flags.items() if k in INCIDENT_FLAGS}

    if args.json:
        print(json.dumps(flags, indent=2))
        return

    # Summary output
    active_count = 0
    print("=" * 70)
    print("FEATURE FLAGS")
    print("=" * 70)

    for name, config in sorted(flags.items()):
        default = config.get("defaultVariant", "unknown")
        variants = config.get("variants", {})
        current_value = variants.get(default, "?")
        state = config.get("state", "ENABLED")
        is_incident = name in INCIDENT_FLAGS

        # Determine if flag is "active" (not in its safe/off state)
        is_active = False
        if isinstance(current_value, bool):
            is_active = current_value is True
        elif isinstance(current_value, (int, float)):
            is_active = current_value != 0

        marker = ""
        if is_incident and is_active:
            marker = " [ACTIVE INCIDENT]"
            active_count += 1
        elif is_incident:
            marker = " [incident]"

        print(f"\n  {name}{marker}")
        print(f"    Default: {default} (value: {current_value})")

        if args.verbose:
            variant_strs = [f"{k}={v}" for k, v in variants.items()]
            print(f"    Variants: {', '.join(variant_strs)}")
            if state != "ENABLED":
                print(f"    State: {state}")

    print(f"\n{'=' * 70}")
    print(f"Total: {len(flags)} flags")
    if active_count > 0:
        print(f"ACTIVE INCIDENTS: {active_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
