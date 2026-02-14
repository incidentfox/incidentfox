#!/usr/bin/env python3
"""Migrate integration field names in existing configs to match credential-resolver.

The credential-resolver reads specific field names from config JSON. Some integrations
were originally seeded with different field names in the DB schemas and web UI.
This script renames those fields in any existing node_configurations entries so that
configs saved via the web UI will work with the credential-resolver.

Field renames:
- coralogix: region -> domain
- confluence: api_token -> api_key, url -> domain
- grafana: base_url -> domain
- elasticsearch: url -> domain
- github: token -> api_key, org -> default_org
- gitlab: token -> api_key, url -> domain
- splunk: host -> domain, token -> api_key
- sentry: auth_token -> api_key, base_url -> domain
- kubernetes: kubeconfig -> (no direct rename, different model)
- jira: api_token -> api_key, url -> domain

This script is idempotent -- it only renames if the old field exists and the new
field does not.
"""

import json
import os
import sys

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set")
    sys.exit(1)

# Map of integration_id -> list of (old_field, new_field) renames
FIELD_RENAMES = {
    "coralogix": [("region", "domain")],
    "confluence": [("api_token", "api_key"), ("url", "domain")],
    "grafana": [("base_url", "domain")],
    "elasticsearch": [("url", "domain")],
    "github": [("token", "api_key"), ("org", "default_org")],
    "gitlab": [("token", "api_key"), ("url", "domain")],
    "splunk": [("host", "domain"), ("token", "api_key")],
    "sentry": [("auth_token", "api_key"), ("base_url", "domain")],
    "jira": [("api_token", "api_key"), ("url", "domain")],
}


def main():
    engine = create_engine(DATABASE_URL)
    total_updates = 0

    try:
        with engine.begin() as conn:
            # Get all node_configurations with integrations
            rows = conn.execute(
                text(
                    "SELECT id, org_id, node_id, config_json "
                    "FROM node_configurations "
                    "WHERE config_json ? 'integrations'"
                )
            ).fetchall()

            print(f"Found {len(rows)} node_configurations with integrations")

            for row in rows:
                row_id = row[0]
                org_id = row[1]
                node_id = row[2]
                config = row[3] if isinstance(row[3], dict) else json.loads(row[3])

                integrations = config.get("integrations", {})
                modified = False

                for integration_id, renames in FIELD_RENAMES.items():
                    if integration_id not in integrations:
                        continue

                    int_config = integrations[integration_id]

                    for old_field, new_field in renames:
                        # Only rename if old field exists and new field does not
                        if old_field in int_config and new_field not in int_config:
                            int_config[new_field] = int_config.pop(old_field)
                            modified = True
                            print(
                                f"  [{org_id}/{node_id}] {integration_id}: "
                                f"{old_field} -> {new_field}"
                            )

                if modified:
                    conn.execute(
                        text(
                            "UPDATE node_configurations "
                            "SET config_json = CAST(:config AS jsonb), "
                            "    updated_at = NOW() "
                            "WHERE id = :id"
                        ),
                        {"id": row_id, "config": json.dumps(config)},
                    )
                    total_updates += 1

            # Also update the integration_schemas table to rename fields
            print("\nUpdating integration_schemas table...")
            schema_updates = 0

            for integration_id, renames in FIELD_RENAMES.items():
                result = conn.execute(
                    text("SELECT id, fields FROM integration_schemas WHERE id = :id"),
                    {"id": integration_id},
                )
                schema_row = result.fetchone()
                if not schema_row:
                    continue

                fields = (
                    schema_row[1]
                    if isinstance(schema_row[1], list)
                    else json.loads(schema_row[1])
                )
                schema_modified = False

                for field in fields:
                    field_name = field.get("name")
                    for old_field, new_field in renames:
                        if field_name == old_field:
                            field["name"] = new_field
                            schema_modified = True
                            print(
                                f"  [schema] {integration_id}: "
                                f"field {old_field} -> {new_field}"
                            )

                if schema_modified:
                    conn.execute(
                        text(
                            "UPDATE integration_schemas "
                            "SET fields = CAST(:fields AS jsonb), "
                            "    updated_at = NOW() "
                            "WHERE id = :id"
                        ),
                        {"id": integration_id, "fields": json.dumps(fields)},
                    )
                    schema_updates += 1

        print(
            f"\nDone: {total_updates} config(s) updated, "
            f"{schema_updates} schema(s) updated"
        )

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
