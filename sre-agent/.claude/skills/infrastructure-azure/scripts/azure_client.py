#!/usr/bin/env python3
"""Shared Azure client with proxy support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os
from datetime import datetime


def get_config() -> dict[str, str | None]:
    """Get Azure configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID", ""),
        "resource_group": os.getenv("AZURE_RESOURCE_GROUP"),
    }


def get_credentials():
    """Get Azure credentials.

    Supports:
    1. Service principal (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
    2. DefaultAzureCredential (CLI, managed identity, etc.)
    """
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def get_subscription_id() -> str:
    """Get the Azure subscription ID."""
    sub_id = os.getenv("AZURE_SUBSCRIPTION_ID", "")
    if not sub_id:
        raise RuntimeError("AZURE_SUBSCRIPTION_ID must be set")
    return sub_id


def serialize_value(value):
    """Serialize a value for JSON output."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)
