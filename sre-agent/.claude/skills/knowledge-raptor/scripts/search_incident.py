#!/usr/bin/env python3
"""Incident-aware search: find runbooks and past incidents matching symptoms.

Usage:
    python search_incident.py --symptoms DESCRIPTION [--service SERVICE] [--top-k N]

Examples:
    python search_incident.py --symptoms "pods keep crashing with OOMKilled"
    python search_incident.py --symptoms "503 errors" --service payment-gateway
"""

import argparse
import json
import sys

from raptor_client import raptor_post


def main():
    parser = argparse.ArgumentParser(
        description="Find runbooks and past incidents matching symptoms"
    )
    parser.add_argument(
        "--symptoms",
        required=True,
        help="Description of the symptoms/issue",
    )
    parser.add_argument(
        "--service",
        default="",
        help="Affected service name (optional but recommended)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results per category (default: 5)",
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
            "affected_service": args.service,
            "include_runbooks": True,
            "include_past_incidents": True,
            "top_k": args.top_k,
        }

        data = raptor_post("/api/v1/incident-search", payload)

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            service_label = f" (service: {args.service})" if args.service else ""
            print(f"\nIncident search for: {args.symptoms}{service_label}\n")

            # Runbooks
            runbooks = data.get("runbooks", [])
            if runbooks:
                print(f"--- Runbooks ({len(runbooks)}) ---\n")
                for i, rb in enumerate(runbooks, 1):
                    title = rb.get("title", "Untitled")
                    relevance = rb.get("relevance", 0)
                    text = rb.get("text", "")
                    print(f"{i}. [{relevance:.2f}] {title}")
                    preview = text[:200].replace("\n", " ")
                    if len(text) > 200:
                        preview += "..."
                    print(f"   {preview}")
                    print()

            # Past incidents
            incidents = data.get("past_incidents", [])
            if incidents:
                print(f"--- Past Incidents ({len(incidents)}) ---\n")
                for i, inc in enumerate(incidents, 1):
                    inc_id = inc.get("incident_id", "unknown")
                    relevance = inc.get("relevance", 0)
                    summary = inc.get("summary", "")
                    resolution = inc.get("resolution", "")
                    print(f"{i}. [{relevance:.2f}] {inc_id}")
                    if summary:
                        preview = summary[:200].replace("\n", " ")
                        print(f"   Summary: {preview}")
                    if resolution:
                        preview = resolution[:200].replace("\n", " ")
                        print(f"   Resolution: {preview}")
                    print()

            # Service context
            context = data.get("service_context", [])
            if context:
                print(f"--- Service Context ({len(context)}) ---\n")
                for i, ctx in enumerate(context, 1):
                    text = ctx.get("text", "")
                    relevance = ctx.get("relevance", 0)
                    print(f"{i}. [{relevance:.2f}]")
                    preview = text[:200].replace("\n", " ")
                    if len(text) > 200:
                        preview += "..."
                    print(f"   {preview}")
                    print()

            if not runbooks and not incidents and not context:
                print("No matching runbooks or past incidents found.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
