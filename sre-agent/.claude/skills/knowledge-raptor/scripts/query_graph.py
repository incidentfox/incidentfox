#!/usr/bin/env python3
"""Query the service dependency graph in the knowledge base.

Usage:
    python query_graph.py --entity ENTITY --query-type TYPE [--max-hops N]

Query types: dependencies, dependents, owner, runbooks, incidents, blast_radius

Examples:
    python query_graph.py --entity payment-gateway --query-type blast_radius
    python query_graph.py --entity redis-cache --query-type dependents
    python query_graph.py --entity auth-service --query-type owner
"""

import argparse
import json
import sys

from raptor_client import raptor_post

QUERY_TYPES = [
    "dependencies",
    "dependents",
    "owner",
    "runbooks",
    "incidents",
    "blast_radius",
]


def main():
    parser = argparse.ArgumentParser(description="Query the service dependency graph")
    parser.add_argument(
        "--entity",
        required=True,
        help="Service or entity name to query",
    )
    parser.add_argument(
        "--query-type",
        required=True,
        choices=QUERY_TYPES,
        help="Type of graph query",
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        default=2,
        help="Maximum hops in graph traversal (1-5, default: 2)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        payload = {
            "entity_name": args.entity,
            "query_type": args.query_type,
            "max_hops": args.max_hops,
        }

        data = raptor_post("/api/v1/graph/query", payload)

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"\nGraph query: {args.entity} -> {args.query_type}\n")

            if args.query_type == "dependencies":
                deps = data.get("dependencies", [])
                if deps:
                    print(f"Dependencies ({len(deps)}):")
                    for dep in deps:
                        print(f"  - {dep}")
                else:
                    print("No dependencies found.")

            elif args.query_type == "dependents":
                deps = data.get("dependents", [])
                if deps:
                    print(f"Dependents ({len(deps)}):")
                    for dep in deps:
                        print(f"  - {dep}")
                else:
                    print("No dependents found.")

            elif args.query_type == "owner":
                owner = data.get("owner", {})
                if owner:
                    print(f"Owner: {owner.get('team', 'unknown')}")
                    if owner.get("entity_id"):
                        print(f"Entity ID: {owner['entity_id']}")
                else:
                    print("No owner information found.")

            elif args.query_type == "runbooks":
                runbooks = data.get("runbooks", [])
                if runbooks:
                    print(f"Runbooks ({len(runbooks)}):")
                    for rb in runbooks:
                        rb_id = rb.get("runbook_id", "unknown")
                        props = rb.get("properties", {})
                        print(f"  - {rb_id}")
                        if props:
                            for k, v in props.items():
                                print(f"    {k}: {v}")
                else:
                    print("No runbooks found.")

            elif args.query_type == "incidents":
                incidents = data.get("incidents", [])
                if incidents:
                    print(f"Incidents ({len(incidents)}):")
                    for inc in incidents:
                        inc_id = inc.get("incident_id", "unknown")
                        props = inc.get("properties", {})
                        print(f"  - {inc_id}")
                        if props:
                            for k, v in props.items():
                                print(f"    {k}: {v}")
                else:
                    print("No incidents found.")

            elif args.query_type == "blast_radius":
                blast = data.get("blast_radius", {})
                affected = data.get("affected_services", [])
                if blast or affected:
                    if blast.get("direct_dependents"):
                        print(f"Direct dependents: {blast['direct_dependents']}")
                    if blast.get("total_affected"):
                        print(f"Total affected: {blast['total_affected']}")
                    if affected:
                        print(f"\nAffected services ({len(affected)}):")
                        for svc in affected:
                            print(f"  - {svc}")
                else:
                    print("No blast radius information found.")

            hint = data.get("hint")
            if hint:
                print(f"\nHint: {hint}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
