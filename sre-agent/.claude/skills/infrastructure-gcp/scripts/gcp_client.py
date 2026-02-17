#!/usr/bin/env python3
"""Shared GCP client with credential support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os


def get_config() -> dict[str, str | None]:
    """Get GCP configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "project_id": os.getenv("GCP_PROJECT_ID", ""),
    }


def get_project_id() -> str:
    """Get the GCP project ID."""
    project_id = os.getenv("GCP_PROJECT_ID", "")
    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set")
    return project_id


def get_credentials():
    """Get GCP credentials.

    Supports:
    1. Service account key (GCP_SERVICE_ACCOUNT_KEY env var)
    2. Application default credentials
    """
    sa_key = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
    if sa_key:
        from google.oauth2 import service_account

        credentials_dict = json.loads(sa_key)
        return service_account.Credentials.from_service_account_info(credentials_dict)

    from google.auth import default

    credentials, _ = default()
    return credentials


def build_service(service_name: str, version: str):
    """Build a Google API service client."""
    from googleapiclient import discovery

    return discovery.build(service_name, version, credentials=get_credentials())


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)
