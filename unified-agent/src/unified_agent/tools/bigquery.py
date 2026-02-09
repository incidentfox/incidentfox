"""Google BigQuery data warehouse tools."""

import json
import os
from typing import Any

import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_bigquery_config() -> str:
    """Get BigQuery configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("BIGQUERY_SERVICE_ACCOUNT_KEY") and os.getenv("BIGQUERY_PROJECT_ID"):
        return {
            "service_account_key": os.getenv("BIGQUERY_SERVICE_ACCOUNT_KEY"),
            "project_id": os.getenv("BIGQUERY_PROJECT_ID"),
            "dataset": os.getenv("BIGQUERY_DATASET"),
        }

    # 3. Not configured - raise error
    return {"error": "bigquery not configured"}


def _get_bigquery_client():
    """Get BigQuery client."""
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        config = _get_bigquery_config()

        # Parse service account key JSON
        credentials_dict = json.loads(config["service_account_key"])
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict
        )

        return bigquery.Client(credentials=credentials, project=config["project_id"])

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "bigquery",
            "google-cloud-bigquery not installed. Install with: pip install google-cloud-bigquery",
        )


@function_tool
def bigquery_query(
    query: str, dataset: str | None = None, max_results: int = 1000
) -> str:
    """
    Execute a SQL query on BigQuery.

    Args:
        query: SQL query to execute
        dataset: Optional dataset to use (overrides config default)
        max_results: Maximum number of rows to return

    Returns:
        Query results including rows and metadata
    """
    try:
        client = _get_bigquery_client()
        config = _get_bigquery_config()

        # Add dataset to query if specified or in config
        default_dataset = dataset or config.get("dataset")

        job_config = None
        if default_dataset:
            from google.cloud import bigquery

            job_config = bigquery.QueryJobConfig(
                default_dataset=f"{config['project_id']}.{default_dataset}"
            )

        query_job = client.query(query, job_config=job_config)
        results = query_job.result(max_results=max_results)

        rows = []
        for row in results:
            rows.append(dict(row))

        logger.info("bigquery_query_executed", rows=len(rows), query_hash=hash(query))

        return {
            "rows": rows,
            "row_count": len(rows),
            "total_rows": results.total_rows,
            "schema": [
                {"name": field.name, "type": field.field_type}
                for field in results.schema
            ],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("bigquery_query_failed", error=str(e))
        return json.dumps({"ok": False, "error": "bigquery_query"})


@function_tool
def bigquery_list_datasets() -> str:
    """
    List all datasets in the BigQuery project.

    Returns:
        List of datasets with metadata
    """
    try:
        client = _get_bigquery_client()

        datasets = []
        for dataset in client.list_datasets():
            datasets.append(
                {
                    "dataset_id": dataset.dataset_id,
                    "full_name": dataset.full_dataset_id,
                    "location": dataset.location,
                }
            )

        logger.info("bigquery_datasets_listed", count=len(datasets))
        return datasets

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("bigquery_list_datasets_failed", error=str(e))
        return json.dumps({"ok": False, "error": "bigquery_list_datasets"})


@function_tool
def bigquery_list_tables(dataset: str) -> str:
    """
    List all tables in a BigQuery dataset.

    Args:
        dataset: Dataset ID

    Returns:
        List of tables with metadata
    """
    try:
        client = _get_bigquery_client()
        config = _get_bigquery_config()

        dataset_ref = f"{config['project_id']}.{dataset}"
        tables = []

        for table in client.list_tables(dataset_ref):
            # Get table details
            table_ref = client.get_table(f"{dataset_ref}.{table.table_id}")
            tables.append(
                {
                    "table_id": table.table_id,
                    "full_name": f"{dataset_ref}.{table.table_id}",
                    "table_type": table.table_type,
                    "num_rows": table_ref.num_rows,
                    "num_bytes": table_ref.num_bytes,
                    "created": str(table_ref.created),
                    "modified": str(table_ref.modified),
                }
            )

        logger.info("bigquery_tables_listed", dataset=dataset, count=len(tables))
        return tables

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("bigquery_list_tables_failed", error=str(e), dataset=dataset)
        return json.dumps({"ok": False, "error": "bigquery_list_tables"})


@function_tool
def bigquery_get_table_schema(dataset: str, table: str) -> str:
    """
    Get schema information for a BigQuery table.

    Args:
        dataset: Dataset ID
        table: Table ID

    Returns:
        Table schema with field definitions
    """
    try:
        client = _get_bigquery_client()
        config = _get_bigquery_config()

        table_ref = f"{config['project_id']}.{dataset}.{table}"
        table_obj = client.get_table(table_ref)

        schema = []
        for field in table_obj.schema:
            schema.append(
                {
                    "name": field.name,
                    "type": field.field_type,
                    "mode": field.mode,
                    "description": field.description or "",
                }
            )

        logger.info(
            "bigquery_schema_retrieved",
            dataset=dataset,
            table=table,
            fields=len(schema),
        )

        return {
            "dataset": dataset,
            "table": table,
            "num_rows": table_obj.num_rows,
            "num_bytes": table_obj.num_bytes,
            "schema": schema,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "bigquery_get_schema_failed", error=str(e), dataset=dataset, table=table
        )
        return json.dumps({"ok": False, "error": "bigquery_get_table_schema"})


# List of all BigQuery tools for registration
BIGQUERY_TOOLS = [
    bigquery_query,
    bigquery_list_datasets,
    bigquery_list_tables,
    bigquery_get_table_schema,
]


# Register tools
register_tool("bigquery_query", bigquery_query)
register_tool("bigquery_list_datasets", bigquery_list_datasets)
register_tool("bigquery_list_tables", bigquery_list_tables)
register_tool("bigquery_get_table_schema", bigquery_get_table_schema)
