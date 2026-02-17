#!/usr/bin/env python3
"""Shared MySQL client with credential support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os


def get_config() -> dict[str, str | None]:
    """Get MySQL configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "host": os.getenv("MYSQL_HOST", ""),
        "port": os.getenv("MYSQL_PORT", "3306"),
        "database": os.getenv("MYSQL_DATABASE", ""),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "ssl_mode": os.getenv("MYSQL_SSL_MODE", "PREFERRED"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
    }


def get_connection():
    """Get a MySQL connection."""
    import mysql.connector

    config = get_config()

    conn_kwargs = {
        "host": config["host"],
        "port": int(config.get("port") or 3306),
        "database": config["database"],
        "user": config.get("user"),
        "password": config.get("password"),
        "charset": config.get("charset") or "utf8mb4",
        "use_unicode": True,
        "autocommit": True,
    }

    ssl_mode = config.get("ssl_mode", "PREFERRED")
    if ssl_mode and ssl_mode.upper() not in ("DISABLED", "NONE"):
        conn_kwargs["ssl_disabled"] = False
    else:
        conn_kwargs["ssl_disabled"] = True

    return mysql.connector.connect(**conn_kwargs)


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)
