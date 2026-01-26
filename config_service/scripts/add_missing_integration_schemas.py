#!/usr/bin/env python3
"""Add missing integration schemas to the database.

This script adds schemas for integrations that have tools defined but no schema:
- Snowflake
- Coralogix
- AWS
- Sentry
- PagerDuty (if not exists)
- Splunk
- Jira
- GitLab
- Linear
- Notion
- Microsoft Teams
- Elasticsearch
- Confluence
"""

import os
import sys

from sqlalchemy import create_engine, text

# Database connection from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set")
    sys.exit(1)

# All missing integration schemas
INTEGRATION_SCHEMAS = [
    {
        "id": "snowflake",
        "name": "Snowflake",
        "category": "data-warehouse",
        "description": "Snowflake data warehouse for SQL analytics and incident data queries",
        "docs_url": "https://docs.snowflake.com/",
        "display_order": 30,
        "featured": True,
        "fields": [
            {
                "name": "account",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Snowflake account identifier (e.g., xy12345.us-east-1)",
                "placeholder": "xy12345.us-east-1",
            },
            {
                "name": "user",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Snowflake username",
            },
            {
                "name": "password",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Snowflake password",
            },
            {
                "name": "warehouse",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Default warehouse to use",
                "placeholder": "COMPUTE_WH",
            },
            {
                "name": "database",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default database (team can override)",
            },
            {
                "name": "schema",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default schema (team can override)",
                "default_value": "PUBLIC",
            },
            {
                "name": "role",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "Role to use for queries",
            },
        ],
    },
    {
        "id": "coralogix",
        "name": "Coralogix",
        "category": "observability",
        "description": "Coralogix observability platform for logs, metrics, and traces",
        "docs_url": "https://coralogix.com/docs/",
        "display_order": 15,
        "featured": True,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Coralogix API key (Alerts, Rules & Tags API Key)",
                "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            },
            {
                "name": "region",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Coralogix region (e.g., cx498.coralogix.com, eu2.coralogix.com)",
                "placeholder": "cx498.coralogix.com",
            },
            {
                "name": "application",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default application filter",
            },
            {
                "name": "subsystem",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default subsystem filter",
            },
        ],
    },
    {
        "id": "aws",
        "name": "AWS",
        "category": "cloud",
        "description": "Amazon Web Services for EC2, ECS, CloudWatch, and other AWS resources",
        "docs_url": "https://docs.aws.amazon.com/",
        "display_order": 40,
        "featured": True,
        "fields": [
            {
                "name": "access_key_id",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "AWS Access Key ID (optional if using IAM roles)",
            },
            {
                "name": "secret_access_key",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "AWS Secret Access Key (optional if using IAM roles)",
            },
            {
                "name": "region",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Default AWS region",
                "default_value": "us-east-1",
            },
            {
                "name": "role_arn",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "IAM Role ARN to assume (for cross-account access)",
            },
            {
                "name": "session_token",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "AWS Session Token (for temporary credentials)",
            },
        ],
    },
    {
        "id": "sentry",
        "name": "Sentry",
        "category": "observability",
        "description": "Sentry error tracking and performance monitoring",
        "docs_url": "https://docs.sentry.io/",
        "display_order": 25,
        "featured": False,
        "fields": [
            {
                "name": "auth_token",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Sentry Auth Token with project:read and issue:read scopes",
            },
            {
                "name": "organization",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Sentry organization slug",
            },
            {
                "name": "project",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default project slug (team can override)",
            },
            {
                "name": "base_url",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "Sentry API base URL (for self-hosted)",
                "default_value": "https://sentry.io/api/0",
            },
        ],
    },
    {
        "id": "splunk",
        "name": "Splunk",
        "category": "observability",
        "description": "Splunk for log search and analysis",
        "docs_url": "https://docs.splunk.com/",
        "display_order": 22,
        "featured": False,
        "fields": [
            {
                "name": "host",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Splunk server hostname",
                "placeholder": "splunk.company.com",
            },
            {
                "name": "port",
                "type": "integer",
                "required": False,
                "level": "org",
                "description": "Splunk REST API port",
                "default_value": 8089,
            },
            {
                "name": "token",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Splunk authentication token",
            },
            {
                "name": "index",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default index to search",
            },
            {
                "name": "verify_ssl",
                "type": "boolean",
                "required": False,
                "level": "org",
                "description": "Verify SSL certificates",
                "default_value": True,
            },
        ],
    },
    {
        "id": "jira",
        "name": "Jira",
        "category": "project-management",
        "description": "Atlassian Jira for issue tracking and incident tickets",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
        "display_order": 50,
        "featured": False,
        "fields": [
            {
                "name": "url",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Jira instance URL",
                "placeholder": "https://company.atlassian.net",
            },
            {
                "name": "email",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Jira account email",
            },
            {
                "name": "api_token",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Jira API token",
            },
            {
                "name": "project_key",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default project key",
            },
        ],
    },
    {
        "id": "gitlab",
        "name": "GitLab",
        "category": "scm",
        "description": "GitLab for repository analysis and change correlation",
        "docs_url": "https://docs.gitlab.com/ee/api/",
        "display_order": 45,
        "featured": False,
        "fields": [
            {
                "name": "url",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "GitLab instance URL",
                "default_value": "https://gitlab.com",
            },
            {
                "name": "token",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "GitLab personal access token with api scope",
            },
            {
                "name": "default_project",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default project path (e.g., group/project)",
            },
        ],
    },
    {
        "id": "linear",
        "name": "Linear",
        "category": "project-management",
        "description": "Linear for issue tracking",
        "docs_url": "https://developers.linear.app/docs",
        "display_order": 55,
        "featured": False,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Linear API key",
            },
            {
                "name": "team_id",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default team ID",
            },
        ],
    },
    {
        "id": "notion",
        "name": "Notion",
        "category": "collaboration",
        "description": "Notion for runbooks and documentation",
        "docs_url": "https://developers.notion.com/",
        "display_order": 60,
        "featured": False,
        "fields": [
            {
                "name": "api_key",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Notion integration API key",
            },
            {
                "name": "default_database_id",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default database ID for queries",
            },
        ],
    },
    {
        "id": "msteams",
        "name": "Microsoft Teams",
        "category": "communication",
        "description": "Microsoft Teams for incident notifications and collaboration",
        "docs_url": "https://docs.microsoft.com/en-us/graph/api/resources/teams-api-overview",
        "display_order": 65,
        "featured": False,
        "fields": [
            {
                "name": "webhook_url",
                "type": "secret",
                "required": True,
                "level": "team",
                "description": "Teams Incoming Webhook URL",
            },
            {
                "name": "tenant_id",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "Azure AD Tenant ID (for Graph API)",
            },
            {
                "name": "client_id",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "Azure AD App Client ID",
            },
            {
                "name": "client_secret",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "Azure AD App Client Secret",
            },
        ],
    },
    {
        "id": "elasticsearch",
        "name": "Elasticsearch",
        "category": "observability",
        "description": "Elasticsearch for log search and analytics",
        "docs_url": "https://www.elastic.co/guide/en/elasticsearch/reference/current/",
        "display_order": 20,
        "featured": False,
        "fields": [
            {
                "name": "url",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Elasticsearch URL",
                "placeholder": "https://elasticsearch:9200",
            },
            {
                "name": "api_key",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "Elasticsearch API key (optional if using basic auth)",
            },
            {
                "name": "username",
                "type": "string",
                "required": False,
                "level": "org",
                "description": "Elasticsearch username",
            },
            {
                "name": "password",
                "type": "secret",
                "required": False,
                "level": "org",
                "description": "Elasticsearch password",
            },
            {
                "name": "index_pattern",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default index pattern",
                "default_value": "logs-*",
            },
            {
                "name": "verify_ssl",
                "type": "boolean",
                "required": False,
                "level": "org",
                "description": "Verify SSL certificates",
                "default_value": True,
            },
        ],
    },
    {
        "id": "confluence",
        "name": "Confluence",
        "category": "collaboration",
        "description": "Atlassian Confluence for runbooks and documentation",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/",
        "display_order": 62,
        "featured": False,
        "fields": [
            {
                "name": "url",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Confluence instance URL",
                "placeholder": "https://company.atlassian.net/wiki",
            },
            {
                "name": "email",
                "type": "string",
                "required": True,
                "level": "org",
                "description": "Confluence account email",
            },
            {
                "name": "api_token",
                "type": "secret",
                "required": True,
                "level": "org",
                "description": "Confluence API token",
            },
            {
                "name": "space_key",
                "type": "string",
                "required": False,
                "level": "team",
                "description": "Default space key",
            },
        ],
    },
]


def main():
    """Add missing integration schemas to database."""
    import json

    engine = create_engine(DATABASE_URL)
    added_count = 0
    skipped_count = 0

    try:
        with engine.begin() as conn:
            for schema in INTEGRATION_SCHEMAS:
                # Check if already exists
                result = conn.execute(
                    text("SELECT id FROM integration_schemas WHERE id = :id"),
                    {"id": schema["id"]},
                )
                if result.fetchone():
                    print(f"  [skip] {schema['id']} already exists")
                    skipped_count += 1
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
                        "docs_url": schema.get("docs_url"),
                        "icon_url": schema.get("icon_url"),
                        "display_order": schema["display_order"],
                        "featured": schema.get("featured", False),
                        "fields": json.dumps(schema["fields"]),
                    },
                )
                print(f"  [add] {schema['id']}")
                added_count += 1

        print(f"\nDone: {added_count} added, {skipped_count} skipped")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
