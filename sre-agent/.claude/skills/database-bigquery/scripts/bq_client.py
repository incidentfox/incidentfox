#!/usr/bin/env python3
"""Shared BigQuery client with credential support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os


def get_config() -> dict[str, str | None]:
    """Get BigQuery configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "project_id": os.getenv("BIGQUERY_PROJECT_ID", ""),
        "dataset": os.getenv("BIGQUERY_DATASET"),
    }


def get_project_id() -> str:
    """Get the BigQuery project ID."""
    project_id = os.getenv("BIGQUERY_PROJECT_ID", "")
    if not project_id:
        raise RuntimeError("BIGQUERY_PROJECT_ID must be set")
    return project_id


def get_client():
    """Get a BigQuery client."""
    from google.cloud import bigquery

    sa_key = os.getenv("BIGQUERY_SERVICE_ACCOUNT_KEY")
    if sa_key:
        from google.oauth2 import service_account

        credentials_dict = json.loads(sa_key)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict
        )
        return bigquery.Client(credentials=credentials, project=get_project_id())

    return bigquery.Client(project=get_project_id())


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)
