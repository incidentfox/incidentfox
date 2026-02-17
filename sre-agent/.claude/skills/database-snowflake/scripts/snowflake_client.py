#!/usr/bin/env python3
"""Shared Snowflake client with credential support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os


def get_config() -> dict[str, str | None]:
    """Get Snowflake configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "account": os.getenv("SNOWFLAKE_ACCOUNT", ""),
        "username": os.getenv("SNOWFLAKE_USERNAME"),
        "password": os.getenv("SNOWFLAKE_PASSWORD"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
        "database": os.getenv("SNOWFLAKE_DATABASE"),
        "schema": os.getenv("SNOWFLAKE_SCHEMA"),
    }


def get_connection():
    """Get a Snowflake connection."""
    import snowflake.connector

    config = get_config()

    return snowflake.connector.connect(
        account=config["account"],
        user=config.get("username") or config.get("user"),
        password=config["password"],
        warehouse=config.get("warehouse") or "COMPUTE_WH",
        database=config.get("database"),
        schema=config.get("schema"),
    )


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)
