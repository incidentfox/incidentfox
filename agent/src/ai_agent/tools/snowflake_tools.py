"""
Snowflake tools for querying business context and incident enrichment data.
"""

import json
import logging
import os

from ..core.config_required import handle_integration_not_configured
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError

logger = logging.getLogger(__name__)


def get_snowflake_config() -> dict:
    """
    Get Snowflake configuration from execution context.

    Priority:
    1. Execution context (production, multi-tenant safe)
    2. Environment variables (dev/testing fallback)

    Returns:
        Snowflake configuration dict

    Raises:
        IntegrationNotConfiguredError: If integration not configured
    """
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("snowflake")
        if config and config.get("account"):
            logger.debug(
                "snowflake_config_from_context",
                org_id=context.org_id,
                team_node_id=context.team_node_id,
            )
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("SNOWFLAKE_ACCOUNT"):
        logger.debug("snowflake_config_from_env")
        return {
            "account": os.getenv("SNOWFLAKE_ACCOUNT"),
            "username": os.getenv("SNOWFLAKE_USERNAME"),
            "password": os.getenv("SNOWFLAKE_PASSWORD"),
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
            "database": os.getenv("SNOWFLAKE_DATABASE", "INCIDENT_ENRICHMENT_DB"),
            "schema": os.getenv("SNOWFLAKE_SCHEMA", "INCIDENT_ENRICHMENT_DEMO"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="snowflake",
        tool_id="run_snowflake_query",
        missing_fields=["account", "username", "password", "warehouse"],
    )


def _get_snowflake_connection():
    """Create a Snowflake connection using current config."""
    try:
        import snowflake.connector
    except ImportError:
        raise ImportError(
            "snowflake-connector-python is required. Install with: pip install snowflake-connector-python"
        )

    try:
        config = get_snowflake_config()
    except IntegrationNotConfiguredError:
        raise

    return snowflake.connector.connect(
        account=config["account"],
        user=config.get("username") or config.get("user"),  # Support both field names
        password=config["password"],
        warehouse=config.get("warehouse", "COMPUTE_WH"),
        database=config.get("database", "INCIDENT_ENRICHMENT_DB"),
        schema=config.get("schema", "INCIDENT_ENRICHMENT_DEMO"),
    )


def run_snowflake_query(query: str, limit: int = 100) -> str:
    """
    Execute a SQL query against Snowflake and return results.

    Args:
        query: SQL query to execute. Should be a SELECT query.
        limit: Maximum number of rows to return (default 100).

    Returns:
        JSON string containing query results with columns and rows.
    """
    logger.info(f"Executing Snowflake query: {query[:100]}...")

    try:
        conn = _get_snowflake_connection()
        cursor = conn.cursor()

        # Add limit if not present
        query_lower = query.lower().strip()
        if "limit" not in query_lower:
            query = f"{query.rstrip(';')} LIMIT {limit}"

        cursor.execute(query)

        # Get column names
        columns = [desc[0] for desc in cursor.description]

        # Fetch rows
        rows = cursor.fetchall()

        # Convert to list of dicts
        results = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                val = row[i]
                # Handle special types
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                elif isinstance(val, bytes):
                    val = val.decode("utf-8", errors="replace")
                row_dict[col] = val
            results.append(row_dict)

        cursor.close()
        conn.close()

        return json.dumps(
            {
                "success": True,
                "row_count": len(results),
                "columns": columns,
                "rows": results,
            },
            indent=2,
            default=str,
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "run_snowflake_query", "snowflake")
    except Exception as e:
        logger.error(f"Snowflake query failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


def get_recent_incidents(limit: int = 10) -> str:
    """
    Get recent incidents from the incident enrichment database.

    Args:
        limit: Number of incidents to return (default 10).

    Returns:
        JSON with recent incidents including severity, title, and root cause.
    """
    query = f"""
    SELECT incident_id, sev, title, started_at, resolved_at, root_cause_type, status, env, region
    FROM fact_incident 
    ORDER BY started_at DESC 
    LIMIT {limit}
    """
    return run_snowflake_query(query, limit)


def get_incident_customer_impact(incident_id: str | None = None) -> str:
    """
    Get customer impact for incidents, especially enterprise customers.

    Args:
        incident_id: Optional specific incident ID. If not provided, returns all recent impacts.

    Returns:
        JSON with customer names, tiers, ARR at risk, and incident details.
    """
    if incident_id:
        where_clause = f"WHERE i.incident_id = '{incident_id}'"
    else:
        where_clause = "WHERE c.tier = 'enterprise'"

    query = f"""
    SELECT 
        c.customer_name, 
        c.tier,
        c.arr_usd, 
        i.incident_id,
        i.title,
        i.sev,
        ic.estimated_arr_at_risk_usd,
        ic.impacted_requests,
        ic.error_rate,
        ic.latency_p95_ms
    FROM fact_incident_customer_impact ic
    JOIN dim_customer c ON ic.customer_id = c.customer_id
    JOIN fact_incident i ON ic.incident_id = i.incident_id
    {where_clause}
    ORDER BY ic.estimated_arr_at_risk_usd DESC
    LIMIT 20
    """
    return run_snowflake_query(query, 20)


def get_deployment_incidents() -> str:
    """
    Get incidents caused by deployments, with deployment details.

    Returns:
        JSON with deployment commits, authors, and associated incidents.
    """
    query = """
    SELECT 
        d.deployment_id,
        d.commit_sha, 
        d.author, 
        d.change_type,
        d.service_id,
        s.service_name,
        d.started_at as deployed_at,
        i.incident_id,
        i.title, 
        i.sev,
        i.started_at
    FROM fact_incident i
    JOIN fact_deployment d ON i.deployment_id = d.deployment_id
    LEFT JOIN dim_service s ON d.service_id = s.service_id
    WHERE i.root_cause_type = 'deployment'
    ORDER BY i.started_at DESC
    LIMIT 15
    """
    return run_snowflake_query(query, 15)


def get_customer_info(
    customer_name: str | None = None, customer_id: str | None = None
) -> str:
    """
    Get customer details including tier, ARR, and risk information.

    Args:
        customer_name: Customer name to search (partial match).
        customer_id: Specific customer ID.

    Returns:
        JSON with customer details.
    """
    if customer_id:
        where_clause = f"WHERE customer_id = '{customer_id}'"
    elif customer_name:
        where_clause = f"WHERE LOWER(customer_name) LIKE LOWER('%{customer_name}%')"
    else:
        where_clause = "WHERE tier = 'enterprise'"

    query = f"""
    SELECT 
        customer_id,
        customer_name,
        tier,
        arr_usd,
        customer_region,
        industry,
        sla,
        onboard_date
    FROM dim_customer
    {where_clause}
    ORDER BY arr_usd DESC
    LIMIT 10
    """
    return run_snowflake_query(query, 10)


def get_incident_timeline(incident_id: str) -> str:
    """
    Get detailed timeline and context for a specific incident.

    Args:
        incident_id: The incident ID to look up.

    Returns:
        JSON with incident details, customer impacts, and related deployments.
    """
    # Get incident details
    incident_query = f"""
    SELECT 
        i.*,
        d.commit_sha,
        d.author as deployment_author,
        s.service_name,
        d.change_type
    FROM fact_incident i
    LEFT JOIN fact_deployment d ON i.deployment_id = d.deployment_id
    LEFT JOIN dim_service s ON d.service_id = s.service_id
    WHERE i.incident_id = '{incident_id}'
    """

    return run_snowflake_query(incident_query, 1)


def search_incidents_by_service(service_name: str) -> str:
    """
    Search for historical incidents affecting a specific service.

    Args:
        service_name: Service name from your environment (e.g., "api", "payments", "frontend").
                      Use the service name mentioned in the incident or alert.

    Returns:
        JSON with incidents: id, severity, title, started_at, root_cause_type, status.
        Use this to find patterns in past incidents for the same service.
    """
    query = f"""
    SELECT 
        i.incident_id,
        i.sev,
        i.title,
        i.started_at,
        i.resolved_at,
        i.root_cause_type,
        i.status,
        s.service_name
    FROM fact_incident i
    LEFT JOIN fact_deployment d ON i.deployment_id = d.deployment_id
    LEFT JOIN dim_service s ON d.service_id = s.service_id
    WHERE s.service_name ILIKE '%{service_name}%'
       OR i.title ILIKE '%{service_name}%'
    ORDER BY i.started_at DESC
    LIMIT 15
    """
    return run_snowflake_query(query, 15)


def snowflake_list_tables(
    database: str | None = None, schema: str | None = None
) -> str:
    """
    List all tables in a Snowflake database/schema.

    Args:
        database: Database name (uses default if not specified)
        schema: Schema name (uses default if not specified)

    Returns:
        List of tables as JSON string
    """
    try:
        conn = _get_snowflake_connection()
        cursor = conn.cursor()

        query = "SHOW TABLES"
        if database:
            query += f" IN DATABASE {database}"
        if schema:
            query += f" IN SCHEMA {schema}"

        cursor.execute(query)
        tables = cursor.fetchall()

        result = []
        for table in tables:
            result.append(
                {
                    "name": table[1],  # table_name
                    "database": table[2],  # database_name
                    "schema": table[3],  # schema_name
                    "owner": table[4],  # owner
                    "rows": table[5],  # rows
                    "bytes": table[6],  # bytes
                    "created": str(table[0]),  # created_on
                }
            )

        return json.dumps(
            {
                "table_count": len(result),
                "tables": result,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "snowflake_list_tables", "snowflake"
        )
    except Exception as e:
        logger.error(f"failed_to_list_snowflake_tables: {e}")
        return json.dumps({"error": str(e)})
    finally:
        cursor.close()
        conn.close()


def snowflake_describe_table(
    table_name: str, database: str | None = None, schema: str | None = None
) -> str:
    """
    Get column details for a Snowflake table.

    Args:
        table_name: Table name
        database: Database name (uses default if not specified)
        schema: Schema name (uses default if not specified)

    Returns:
        Table schema as JSON string
    """
    try:
        conn = _get_snowflake_connection()
        cursor = conn.cursor()

        full_table_name = table_name
        if database and schema:
            full_table_name = f"{database}.{schema}.{table_name}"
        elif schema:
            full_table_name = f"{schema}.{table_name}"

        cursor.execute(f"DESCRIBE TABLE {full_table_name}")
        columns = cursor.fetchall()

        result = []
        for col in columns:
            result.append(
                {
                    "name": col[0],
                    "type": col[1],
                    "kind": col[2],
                    "null": col[3] == "Y",
                    "default": col[4],
                    "primary_key": col[5] == "Y",
                    "unique_key": col[6] == "Y",
                }
            )

        return json.dumps(
            {
                "table": table_name,
                "column_count": len(result),
                "columns": result,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "snowflake_describe_table", "snowflake"
        )
    except Exception as e:
        logger.error(f"failed_to_describe_snowflake_table: {e}")
        return json.dumps({"error": str(e), "table": table_name})
    finally:
        cursor.close()
        conn.close()


def snowflake_bulk_export(
    query: str,
    output_format: str = "csv",
    stage_name: str = "@~",
    file_prefix: str = "export",
) -> str:
    """
    Export query results to Snowflake stage for bulk data transfer.

    Args:
        query: SQL query to export
        output_format: Output format (csv, json, parquet)
        stage_name: Snowflake stage name (defaults to user stage @~)
        file_prefix: Prefix for output files

    Returns:
        Export details as JSON string
    """
    try:
        conn = _get_snowflake_connection()
        cursor = conn.cursor()

        # Create a temp table from query
        temp_table = f"temp_export_{file_prefix}"
        cursor.execute(f"CREATE TEMPORARY TABLE {temp_table} AS {query}")

        # Copy to stage
        file_format = (
            "TYPE=CSV COMPRESSION=GZIP"
            if output_format == "csv"
            else f"TYPE={output_format.upper()}"
        )
        copy_query = f"""
            COPY INTO {stage_name}/{file_prefix}
            FROM {temp_table}
            FILE_FORMAT = ({file_format})
            OVERWRITE = TRUE
        """

        cursor.execute(copy_query)
        result = cursor.fetchone()

        return json.dumps(
            {
                "status": "success",
                "stage": stage_name,
                "file_prefix": file_prefix,
                "format": output_format,
                "rows_exported": result[0] if result else 0,
                "download_url": f"snowflake://{stage_name}/{file_prefix}*",
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "snowflake_bulk_export", "snowflake"
        )
    except Exception as e:
        logger.error(f"failed_to_bulk_export: {e}")
        return json.dumps({"error": str(e)})
    finally:
        cursor.close()
        conn.close()


def get_snowflake_schema() -> str:
    """
    Get the database schema showing all available tables and their columns.

    ⚠️ CALL THIS FIRST before writing any SQL queries!

    This returns the complete schema for INCIDENT_ENRICHMENT_DB.INCIDENT_ENRICHMENT_DEMO
    with all table names, columns, types, and usage tips.

    Key tables:
    - fact_incident: Main incidents with severity, title, root cause
    - fact_incident_customer_impact: Customer impact per incident
    - dim_customer: Customer details (name, tier, ARR)
    - fact_deployment: Deployment records linked to incidents
    - dim_service: Service dimension table

    Returns:
        JSON with all tables, columns, and SQL query tips.
    """
    # Return the known schema to avoid extra queries
    schema = {
        "database": "INCIDENT_ENRICHMENT_DB",
        "schema": "INCIDENT_ENRICHMENT_DEMO",
        "tables": {
            "fact_incident": {
                "description": "Main incident table with all incidents",
                "columns": [
                    "INCIDENT_ID (string, primary key)",
                    "CREATED_AT (timestamp)",
                    "STARTED_AT (timestamp)",
                    "MITIGATED_AT (timestamp)",
                    "RESOLVED_AT (timestamp)",
                    "STATUS (string: resolved, open, investigating)",
                    "SEV (string: SEV-1, SEV-2, SEV-3, SEV-4)",
                    "PRIMARY_SERVICE_ID (string, FK to dim_service)",
                    "ENV (string: prod, staging)",
                    "REGION (string: us-west-2, us-east-1, etc)",
                    "TITLE (string, incident title)",
                    "SUMMARY (string, incident summary)",
                    "ROOT_CAUSE_TYPE (string: deployment, external_dependency, etc)",
                    "DEPLOYMENT_ID (string, FK to fact_deployment)",
                    "EXTERNAL_DEPENDENCY (string)",
                    "CONFIDENCE (float)",
                ],
            },
            "fact_incident_customer_impact": {
                "description": "Customer impact per incident",
                "columns": [
                    "IMPACT_ID (string, primary key)",
                    "INCIDENT_ID (string, FK to fact_incident)",
                    "CUSTOMER_ID (string, FK to dim_customer)",
                    "IMPACT_TYPE (string: latency, errors, etc)",
                    "IMPACTED_REQUESTS (int)",
                    "ERROR_RATE (float, nullable)",
                    "LATENCY_P95_MS (int)",
                    "ESTIMATED_ARR_AT_RISK_USD (float)",
                    "RECORDED_AT (timestamp)",
                ],
            },
            "dim_customer": {
                "description": "Customer dimension table",
                "columns": [
                    "CUSTOMER_ID (string, primary key)",
                    "CUSTOMER_NAME (string)",
                    "TIER (string: enterprise, pro, free)",
                    "ARR_USD (float, annual recurring revenue)",
                    "INDUSTRY (string)",
                    "CUSTOMER_REGION (string: North America, Europe, etc)",
                    "SLA (string: 99.9, 99.99, etc)",
                    "ONBOARD_DATE (date)",
                ],
            },
            "fact_deployment": {
                "description": "Deployment records",
                "columns": [
                    "DEPLOYMENT_ID (string, primary key)",
                    "SERVICE_ID (string, FK to dim_service)",
                    "ENV (string: prod, staging)",
                    "REGION (string)",
                    "STARTED_AT (string, deployment start time)",
                    "FINISHED_AT (string)",
                    "STATUS (string)",
                    "COMMIT_SHA (string)",
                    "PR_NUMBER (int)",
                    "AUTHOR (string)",
                    "CHANGE_TYPE (string)",
                    "RISK_LEVEL (string)",
                ],
                "note": "Join with dim_service to get SERVICE_NAME",
            },
            "dim_service": {
                "description": "Service dimension table",
                "columns": [
                    "SERVICE_ID (string, primary key)",
                    "SERVICE_NAME (string)",
                    "TEAM (string)",
                    "TIER (string)",
                ],
            },
        },
        "usage_tips": [
            "Use fact_incident for incident queries, NOT 'incidents'",
            "Use dim_customer for customer info, NOT 'customers'",
            "Join fact_incident_customer_impact with dim_customer to get ARR at risk",
            "TITLE and SUMMARY contain incident descriptions, NOT 'incident_description'",
        ],
    }
    return json.dumps(schema, indent=2)


# List of all Snowflake tools for registration
SNOWFLAKE_TOOLS = [
    get_snowflake_schema,
    run_snowflake_query,
    snowflake_list_tables,
    snowflake_describe_table,
    snowflake_bulk_export,
    get_recent_incidents,
    get_incident_customer_impact,
    get_deployment_incidents,
    get_customer_info,
    get_incident_timeline,
    search_incidents_by_service,
]
