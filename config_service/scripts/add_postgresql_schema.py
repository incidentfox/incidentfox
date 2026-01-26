#!/usr/bin/env python3
"""Add PostgreSQL integration schema to the database.

This integration supports:
- AWS RDS PostgreSQL
- AWS Aurora PostgreSQL
- Standard PostgreSQL
- Any PostgreSQL-compatible database
"""

import os
import sys

from sqlalchemy import create_engine, text

# Database connection from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set")
    sys.exit(1)


def main():
    """Add PostgreSQL integration schema to database."""
    engine = create_engine(DATABASE_URL)

    try:
        with engine.begin() as conn:
            # Check if PostgreSQL already exists
            result = conn.execute(
                text("SELECT id FROM integration_schemas WHERE id = 'postgresql'")
            )
            if result.fetchone():
                print("PostgreSQL integration schema already exists")
                return

            # Insert PostgreSQL schema
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
                    "id": "postgresql",
                    "name": "PostgreSQL",
                    "category": "data-warehouse",
                    "description": "PostgreSQL database for SQL queries. Works with RDS, Aurora, and standard PostgreSQL.",
                    "docs_url": "https://www.postgresql.org/docs/",
                    "icon_url": None,
                    "display_order": 35,  # After Snowflake (30) and BigQuery (31)
                    "featured": False,
                    "fields": """[
                    {
                        "name": "host",
                        "type": "string",
                        "required": true,
                        "level": "org",
                        "description": "Database host (e.g., mydb.xxxx.us-east-1.rds.amazonaws.com)",
                        "placeholder": "localhost or RDS endpoint"
                    },
                    {
                        "name": "port",
                        "type": "integer",
                        "required": false,
                        "level": "org",
                        "description": "Database port",
                        "default_value": 5432
                    },
                    {
                        "name": "database",
                        "type": "string",
                        "required": true,
                        "level": "org",
                        "description": "Database name",
                        "placeholder": "mydb"
                    },
                    {
                        "name": "user",
                        "type": "string",
                        "required": true,
                        "level": "org",
                        "description": "Database username",
                        "placeholder": "postgres"
                    },
                    {
                        "name": "password",
                        "type": "secret",
                        "required": true,
                        "level": "org",
                        "description": "Database password"
                    },
                    {
                        "name": "schema",
                        "type": "string",
                        "required": false,
                        "level": "team",
                        "description": "Default schema to use",
                        "default_value": "public"
                    },
                    {
                        "name": "ssl_mode",
                        "type": "string",
                        "required": false,
                        "level": "org",
                        "description": "SSL mode (disable, allow, prefer, require, verify-ca, verify-full)",
                        "default_value": "prefer"
                    }
                ]""",
                },
            )

            print("Successfully added PostgreSQL integration schema to database")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
