#!/usr/bin/env python3
"""Find similar past incidents in the knowledge base.

Usage:
    python find_similar.py --symptoms DESCRIPTION [--service SERVICE] [--limit N]

Examples:
    python find_similar.py --symptoms "connection timeouts to database"
    python find_similar.py --symptoms "high memory usage" --service checkout-service
"""

import argparse
import json
import sys

from raptor_client import raptor_post


def main():
    parser = argparse.ArgumentParser(description="Find similar past incidents")
    parser.add_argument(
        "--symptoms",
        required=True,
        help="Description of the symptoms to match",
    )
    parser.add_argument(
        "--service",
        default="",
        help="Filter by service name (optional)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum results (default: 5)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        payload = {
            "symptoms": args.symptoms,
            "service": args.service,
            "limit": args.limit,
        }

        data = raptor_post("/api/v1/similar-incidents", payload)

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            incidents = data.get("similar_incidents", [])
            total = data.get("total_found", len(incidents))

            print(f"\nSimilar incidents for: {args.symptoms}")
            if args.service:
                print(f"Service filter: {args.service}")
            print(f"Found: {total}\n")

            if not incidents:
                print("No similar incidents found.")
            else:
                for i, inc in enumerate(incidents, 1):
                    similarity = inc.get("similarity", 0)
                    inc_id = inc.get("incident_id", "unknown")
                    date = inc.get("date", "")
                    symptoms = inc.get("symptoms", "")
                    root_cause = inc.get("root_cause", "")
                    resolution = inc.get("resolution", "")
                    services = inc.get("services_affected", [])

                    print(f"{i}. [{similarity:.2f}] {inc_id}")
                    if date:
                        print(f"   Date: {date}")
                    if services:
                        print(f"   Services: {', '.join(services)}")
                    if symptoms:
                        print(f"   Symptoms: {symptoms[:200]}")
                    if root_cause:
                        print(f"   Root cause: {root_cause[:200]}")
                    if resolution:
                        print(f"   Resolution: {resolution[:200]}")
                    print()

            hint = data.get("hint")
            if hint:
                print(f"Hint: {hint}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
