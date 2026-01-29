#!/usr/bin/env python3
"""
Add meeting transcription integration schemas to the database.

This script adds integration schemas for:
- Fireflies.ai (GraphQL API)
- Circleback (Webhook-based)
- Vexa (Self-hosted, on-prem)
- Otter.ai (REST API)

Usage:
    python scripts/add_meeting_schemas.py
"""

import json
import os
import sys

from sqlalchemy import create_engine, text

# Database connection from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set")
    sys.exit(1)


MEETING_SCHEMAS = [
    {
        "id": "fireflies",
        "name": "Fireflies.ai",
        "category": "meeting",
        "description": "AI meeting transcription and note-taking. Automatically records and transcribes Zoom, Google Meet, and Teams meetings.",
        "docs_url": "https://docs.fireflies.ai/",
        "icon_url": "https://cdn.incidentfox.ai/icons/fireflies.svg",
        "display_order": 100,
        "featured": True,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Fireflies API key from your account settings",
                "placeholder": "ff_...",
            }
        ],
    },
    {
        "id": "circleback",
        "name": "Circleback",
        "category": "meeting",
        "description": "AI meeting assistant that joins your calls and provides automated notes, action items, and transcripts via webhook.",
        "docs_url": "https://circleback.ai/docs/webhook-integration",
        "icon_url": "https://cdn.incidentfox.ai/icons/circleback.svg",
        "display_order": 101,
        "featured": False,
        "fields": [
            {
                "name": "signing_secret",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "Webhook signing secret for verifying Circleback webhooks (optional but recommended)",
                "placeholder": "whsec_...",
            },
            {
                "name": "webhook_url",
                "type": "readonly",
                "required": False,
                "level": "org",
                "description": "Configure this URL in Circleback dashboard to receive meeting data",
                "default_value": "https://orchestrator.incidentfox.ai/webhooks/circleback",
            },
        ],
    },
    {
        "id": "vexa",
        "name": "Vexa (Self-hosted)",
        "category": "meeting",
        "description": "Self-hosted meeting transcription for on-premises deployments. Runs entirely in your environment with no external data transfer.",
        "docs_url": "https://github.com/Vexa-ai/vexa",
        "icon_url": "https://cdn.incidentfox.ai/icons/vexa.svg",
        "display_order": 102,
        "featured": False,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "team",
                "description": "Vexa API key for authentication",
                "placeholder": "vexa_...",
            },
            {
                "name": "api_host",
                "type": "string",
                "required": True,
                "level": "team",
                "description": "Vexa API server URL (e.g., http://vexa.internal:8056)",
                "placeholder": "http://vexa:8056",
                "default_value": "http://localhost:8056",
            },
        ],
    },
    {
        "id": "otter",
        "name": "Otter.ai",
        "category": "meeting",
        "description": "AI meeting assistant for transcription and collaboration. Integrates with Zoom, Google Meet, and Microsoft Teams.",
        "docs_url": "https://otter.ai/integrations",
        "icon_url": "https://cdn.incidentfox.ai/icons/otter.svg",
        "display_order": 103,
        "featured": False,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Otter.ai API key (Enterprise plan required)",
                "placeholder": "otter_...",
            }
        ],
    },
    {
        "id": "recall",
        "name": "Recall.ai",
        "category": "meeting",
        "description": "Real-time meeting transcription for incident war rooms. White-label bot joins Zoom, Google Meet, Teams, and Webex meetings to stream live transcripts to your investigation. SOC 2, HIPAA, GDPR compliant.",
        "docs_url": "https://docs.recall.ai/",
        "icon_url": "https://cdn.incidentfox.ai/icons/recall.svg",
        "display_order": 99,  # Featured, show first
        "featured": True,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Recall.ai API key from dashboard",
                "placeholder": "your_recall_api_key",
            },
            {
                "name": "region",
                "type": "select",
                "required": True,
                "level": "org",
                "description": "Recall.ai region (choose closest to your infrastructure)",
                "options": ["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"],
                "default_value": "us-west-2",
            },
            {
                "name": "webhook_secret",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "Webhook signing secret for verifying Recall.ai webhooks (recommended for production)",
                "placeholder": "whsec_...",
            },
            {
                "name": "bot_name",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "Custom name for the meeting bot (default: IncidentFox Notetaker)",
                "default_value": "IncidentFox Notetaker",
                "placeholder": "IncidentFox Notetaker",
            },
            {
                "name": "bot_image_url",
                "type": "url",
                "required": False,
                "level": "org",
                "description": "Custom avatar image URL for the meeting bot (256x256 PNG recommended)",
                "placeholder": "https://your-cdn.com/bot-avatar.png",
            },
            {
                "name": "webhook_url",
                "type": "readonly",
                "required": False,
                "level": "org",
                "description": "Webhook URL to configure in Recall.ai dashboard for real-time transcripts",
                "default_value": "https://orchestrator.incidentfox.ai/webhooks/recall",
            },
        ],
    },
]


def main():
    """Add meeting integration schemas to database."""
    engine = create_engine(DATABASE_URL)

    try:
        with engine.begin() as conn:
            for schema in MEETING_SCHEMAS:
                # Check if schema already exists
                result = conn.execute(
                    text("SELECT id FROM integration_schemas WHERE id = :id"),
                    {"id": schema["id"]},
                )
                if result.fetchone():
                    print(f"  {schema['name']} integration schema already exists")
                    continue

                # Insert schema
                conn.execute(
                    text("""
                        INSERT INTO integration_schemas (
                            id, name, category, description, docs_url, icon_url,
                            display_order, featured, fields, created_at, updated_at
                        ) VALUES (
                            :id, :name, :category, :description, :docs_url, :icon_url,
                            :display_order, :featured, CAST(:fields AS jsonb), NOW(), NOW()
                        )
                    """),
                    {
                        "id": schema["id"],
                        "name": schema["name"],
                        "category": schema["category"],
                        "description": schema["description"],
                        "docs_url": schema["docs_url"],
                        "icon_url": schema["icon_url"],
                        "display_order": schema["display_order"],
                        "featured": schema["featured"],
                        "fields": json.dumps(schema["fields"]),
                    },
                )
                print(f"  Added {schema['name']} integration schema")

            print("\nSuccessfully added meeting integration schemas to database")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
