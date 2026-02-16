#!/usr/bin/env python3
"""Teach the knowledge base something new learned during an investigation.

The system automatically detects duplicates and contradictions.

Usage:
    python teach.py --content KNOWLEDGE [--type TYPE] [--entities E1,E2] [--confidence N]

Examples:
    python teach.py --content "When payment-gateway shows OOMKilled, check Redis connection pool first"
    python teach.py --content "auth-service falls back to DB sessions when Redis is down (+200ms)" \
        --type factual --entities auth-service,redis-cache --confidence 0.9
"""

import argparse
import json
import sys

from raptor_client import raptor_post

KNOWLEDGE_TYPES = [
    "procedural",
    "factual",
    "temporal",
    "relational",
    "contextual",
    "policy",
    "social",
    "meta",
]


def main():
    parser = argparse.ArgumentParser(
        description="Teach the knowledge base new knowledge"
    )
    parser.add_argument(
        "--content",
        required=True,
        help="Knowledge to teach (minimum 20 characters)",
    )
    parser.add_argument(
        "--type",
        default="procedural",
        choices=KNOWLEDGE_TYPES,
        help="Knowledge type (default: procedural)",
    )
    parser.add_argument(
        "--entities",
        default="",
        help="Comma-separated related entities (e.g., payment-gateway,redis-cache)",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.7,
        help="Confidence score 0-1 (default: 0.7)",
    )
    parser.add_argument(
        "--source",
        default="agent_investigation",
        help="Source of the knowledge (default: agent_investigation)",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Task context (e.g., incident ID, investigation thread)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    if len(args.content) < 20:
        print("Error: Content must be at least 20 characters.", file=sys.stderr)
        sys.exit(1)

    try:
        entities = [e.strip() for e in args.entities.split(",") if e.strip()]

        payload = {
            "content": args.content,
            "knowledge_type": args.type,
            "source": args.source,
            "confidence": args.confidence,
            "related_entities": entities,
            "learned_from": args.source,
            "task_context": args.context,
        }

        data = raptor_post("/api/v1/teach", payload)

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            status = data.get("status", "unknown")
            node_id = data.get("node_id")
            message = data.get("message", "")

            status_icons = {
                "created": "Created",
                "merged": "Merged with existing",
                "duplicate": "Duplicate detected",
                "pending_review": "Pending review",
                "contradiction": "Contradiction detected",
            }

            label = status_icons.get(status, status)
            print(f"\nTeach result: {label}")
            if node_id:
                print(f"Node ID: {node_id}")
            if message:
                print(f"Message: {message}")
            print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
