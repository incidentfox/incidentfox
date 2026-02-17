#!/usr/bin/env python3
"""Shared PostgreSQL client with credential support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os


def get_config() -> dict[str, str | None]:
    """Get PostgreSQL configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "host": os.getenv("POSTGRES_HOST", ""),
        "port": os.getenv("POSTGRES_PORT", "5432"),
        "database": os.getenv("POSTGRES_DATABASE", ""),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "schema": os.getenv("POSTGRES_SCHEMA", "public"),
        "ssl_mode": os.getenv("POSTGRES_SSL_MODE", "prefer"),
    }


def get_connection():
    """Get a PostgreSQL connection."""
    import psycopg2

    config = get_config()

    conn_kwargs = {
        "host": config["host"],
        "port": int(config.get("port") or 5432),
        "database": config["database"],
        "user": config.get("user"),
        "password": config.get("password"),
    }

    ssl_mode = config.get("ssl_mode")
    if ssl_mode and ssl_mode != "disable":
        conn_kwargs["sslmode"] = ssl_mode

    return psycopg2.connect(**conn_kwargs)


def get_default_schema() -> str:
    """Get the default schema name."""
    return os.getenv("POSTGRES_SCHEMA", "public")


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)
