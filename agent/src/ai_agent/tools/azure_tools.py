"""Azure resource inspection and debugging tools."""

import json
import os
from datetime import datetime, timedelta

from agents import function_tool

from ..core.config_required import handle_integration_not_configured
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_azure_credentials():
    """
    Get Azure credentials from execution context or environment.

    Azure credentials can come from:
    1. Execution context (for explicitly configured credentials)
    2. Environment variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID)
    3. Azure CLI cached credentials
    4. Managed Identity (for Azure VMs/App Service)
    """
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    # 1. Try execution context (explicit config)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("azure")
        if config and all(
            k in config
            for k in ["client_id", "client_secret", "tenant_id", "subscription_id"]
        ):
            credential = ClientSecretCredential(
                tenant_id=config["tenant_id"],
                client_id=config["client_id"],
                client_secret=config["client_secret"],
            )
            return credential, config["subscription_id"]

    # 2. Try environment variables
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    if subscription_id:
        try:
            # DefaultAzureCredential tries env vars, CLI, managed identity
            credential = DefaultAzureCredential()
            return credential, subscription_id
        except Exception as e:
            logger.warning("failed_to_create_azure_credential", error=str(e))

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="azure",
        tool_id="azure_tools",
        missing_fields=["subscription_id", "credentials"],
    )


# =============================================================================
# Azure Monitor & Log Analytics (KQL) - CRITICAL FOR TIM
# =============================================================================


@function_tool(strict_mode=False)
def query_log_analytics(
    workspace_id: str,
    query: str,
    timespan: str | None = None,
) -> str:
    """
    Execute a KQL (Kusto Query Language) query against Azure Log Analytics.

    This is the primary tool for querying Azure Monitor logs, including:
    - Application logs, system logs, security logs
    - Performance counters and metrics
    - Custom log data

    Args:
        workspace_id: Log Analytics workspace ID (GUID)
        query: KQL query string (e.g., "AzureDiagnostics | where TimeGenerated > ago(1h) | limit 100")
        timespan: Optional timespan (ISO 8601 duration, e.g., "PT1H" for 1 hour, "P1D" for 1 day)

    Returns:
        Query results as JSON string

    Example queries:
        - "AzureDiagnostics | where Level == 'Error' | limit 50"
        - "Heartbeat | summarize count() by Computer"
        - "Perf | where CounterName == 'Processor Time' | summarize avg(CounterValue) by bin(TimeGenerated, 5m)"
    """
    try:
        from azure.monitor.query import LogsQueryClient

        credential, subscription_id = _get_azure_credentials()
        client = LogsQueryClient(credential)

        # Execute query
        if timespan:
            response = client.query_workspace(
                workspace_id=workspace_id, query=query, timespan=timespan
            )
        else:
            response = client.query_workspace(
                workspace_id=workspace_id,
                query=query,
                timespan=timedelta(hours=24),  # Default to 24 hours
            )

        # Parse results
        if response.status == "Success":
            tables = response.tables
            results = []

            for table in tables:
                rows = []
                for row in table.rows:
                    row_dict = {}
                    for i, column in enumerate(table.columns):
                        value = row[i]
                        # Convert datetime to string for JSON serialization
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        row_dict[column.name] = value
                    rows.append(row_dict)
                results.append(
                    {"name": table.name, "row_count": len(rows), "rows": rows}
                )

            return json.dumps(
                {
                    "workspace_id": workspace_id,
                    "query": query,
                    "status": "Success",
                    "tables": results,
                }
            )
        else:
            return json.dumps(
                {
                    "workspace_id": workspace_id,
                    "query": query,
                    "status": "Partial",
                    "error": "Partial results or query timeout",
                }
            )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "query_log_analytics", "azure")
    except Exception as e:
        logger.error(
            "failed_to_query_log_analytics", error=str(e), workspace_id=workspace_id
        )
        return json.dumps(
            {"error": str(e), "workspace_id": workspace_id, "query": query}
        )


@function_tool(strict_mode=False)
def query_azure_resource_graph(
    query: str, subscriptions: list[str] | None = None
) -> str:
    """
    Query Azure resources using Azure Resource Graph (KQL-based).

    Azure Resource Graph provides fast queries across all Azure resources in your subscriptions.
    Great for finding resources, checking configurations, and compliance queries.

    Args:
        query: KQL query string
        subscriptions: Optional list of subscription IDs (defaults to configured subscription)

    Returns:
        Resource query results as JSON string

    Example queries:
        - "Resources | where type == 'microsoft.compute/virtualmachines' | project name, location, properties.hardwareProfile.vmSize"
        - "Resources | where tags.environment == 'production' | count"
        - "Resources | where type =~ 'microsoft.storage/storageaccounts' | where properties.encryption.keySource != 'Microsoft.Keyvault'"
    """
    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient
        from azure.mgmt.resourcegraph.models import QueryRequest

        credential, subscription_id = _get_azure_credentials()
        client = ResourceGraphClient(credential)

        if not subscriptions:
            subscriptions = [subscription_id]

        # Execute query
        query_request = QueryRequest(subscriptions=subscriptions, query=query)

        response = client.resources(query_request)

        # Convert results to JSON-serializable format
        results = []
        for item in response.data:
            # Convert each item to dict and handle datetime serialization
            item_dict = dict(item)
            for key, value in item_dict.items():
                if isinstance(value, datetime):
                    item_dict[key] = value.isoformat()
            results.append(item_dict)

        return json.dumps(
            {
                "query": query,
                "total_records": response.total_records,
                "count": response.count,
                "result_truncated": response.result_truncated,
                "skip_token": response.skip_token,
                "results": results,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "query_azure_resource_graph", "azure"
        )
    except Exception as e:
        logger.error("failed_to_query_resource_graph", error=str(e))
        return json.dumps({"error": str(e), "query": query})


@function_tool(strict_mode=False)
def get_application_insights_traces(
    app_insights_app_id: str,
    query: str,
    timespan: str | None = None,
) -> str:
    """
    Query Application Insights telemetry data (traces, requests, dependencies, exceptions).

    Application Insights provides APM (Application Performance Monitoring) data.

    Args:
        app_insights_app_id: Application Insights application ID
        query: KQL query string
        timespan: Optional timespan (ISO 8601 duration)

    Returns:
        Telemetry data as JSON string

    Example queries:
        - "requests | where timestamp > ago(1h) | where success == false"
        - "exceptions | summarize count() by type"
        - "dependencies | where duration > 1000 | project timestamp, name, duration"
        - "traces | where severityLevel >= 3 | limit 100"
    """
    try:
        from azure.monitor.query import LogsQueryClient

        credential, _ = _get_azure_credentials()
        client = LogsQueryClient(credential)

        # Application Insights uses the same query API as Log Analytics
        if timespan:
            response = client.query_workspace(
                workspace_id=app_insights_app_id, query=query, timespan=timespan
            )
        else:
            response = client.query_workspace(
                workspace_id=app_insights_app_id,
                query=query,
                timespan=timedelta(hours=24),
            )

        if response.status == "Success":
            tables = response.tables
            results = []

            for table in tables:
                rows = []
                for row in table.rows:
                    row_dict = {}
                    for i, column in enumerate(table.columns):
                        value = row[i]
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        row_dict[column.name] = value
                    rows.append(row_dict)
                results.append(
                    {"name": table.name, "row_count": len(rows), "rows": rows}
                )

            return json.dumps(
                {
                    "app_id": app_insights_app_id,
                    "query": query,
                    "status": "Success",
                    "tables": results,
                }
            )
        else:
            return json.dumps(
                {
                    "app_id": app_insights_app_id,
                    "query": query,
                    "status": "Partial",
                    "error": "Partial results",
                }
            )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "get_application_insights_traces", "azure"
        )
    except Exception as e:
        logger.error(
            "failed_to_query_app_insights", error=str(e), app_id=app_insights_app_id
        )
        return json.dumps({"error": str(e), "app_id": app_insights_app_id})


@function_tool(strict_mode=False)
def get_azure_monitor_metrics(
    resource_id: str,
    metric_names: list[str],
    timespan: str | None = None,
    interval: str = "PT5M",
    aggregations: list[str] | None = None,
) -> str:
    """
    Get Azure Monitor metrics for a resource.

    Args:
        resource_id: Full Azure resource ID
        metric_names: List of metric names (e.g., ["Percentage CPU", "Network In"])
        timespan: Optional timespan (ISO 8601 duration, defaults to PT1H)
        interval: Aggregation interval (ISO 8601 duration, e.g., "PT1M", "PT5M")
        aggregations: List of aggregations (e.g., ["Average", "Maximum", "Minimum"])

    Returns:
        Metric data as JSON string
    """
    try:
        from azure.monitor.query import MetricsQueryClient

        credential, _ = _get_azure_credentials()
        client = MetricsQueryClient(credential)

        if not timespan:
            timespan = timedelta(hours=1)

        if not aggregations:
            aggregations = ["Average"]

        response = client.query_resource(
            resource_uri=resource_id,
            metric_names=metric_names,
            timespan=timespan,
            granularity=interval,
            aggregations=aggregations,
        )

        metrics_data = []
        for metric in response.metrics:
            metric_dict = {
                "name": metric.name,
                "unit": str(metric.unit),
                "timeseries": [],
            }

            for timeseries in metric.timeseries:
                ts_data = {
                    "metadata": (
                        dict(timeseries.metadata_values)
                        if timeseries.metadata_values
                        else {}
                    ),
                    "data": [],
                }

                for data_point in timeseries.data:
                    point = {
                        "timestamp": data_point.timestamp.isoformat(),
                    }
                    if data_point.average is not None:
                        point["average"] = data_point.average
                    if data_point.maximum is not None:
                        point["maximum"] = data_point.maximum
                    if data_point.minimum is not None:
                        point["minimum"] = data_point.minimum
                    if data_point.total is not None:
                        point["total"] = data_point.total
                    if data_point.count is not None:
                        point["count"] = data_point.count

                    ts_data["data"].append(point)

                metric_dict["timeseries"].append(ts_data)

            metrics_data.append(metric_dict)

        return json.dumps(
            {"resource_id": resource_id, "interval": interval, "metrics": metrics_data}
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "get_azure_monitor_metrics", "azure"
        )
    except Exception as e:
        logger.error(
            "failed_to_get_azure_monitor_metrics", error=str(e), resource_id=resource_id
        )
        return json.dumps({"error": str(e), "resource_id": resource_id})


@function_tool(strict_mode=False)
def get_azure_monitor_alerts(resource_group: str | None = None) -> str:
    """
    List Azure Monitor alert rules and their status.

    Args:
        resource_group: Optional resource group name (defaults to all resource groups)

    Returns:
        Alert rules as JSON string
    """
    try:
        from azure.mgmt.monitor import MonitorManagementClient

        credential, subscription_id = _get_azure_credentials()
        client = MonitorManagementClient(credential, subscription_id)

        if resource_group:
            alerts = client.alert_rules.list_by_resource_group(resource_group)
        else:
            # List all alert rules across subscription
            alerts = client.alert_rules.list_by_subscription()

        alert_list = []
        for alert in alerts:
            alert_list.append(
                {
                    "name": alert.name,
                    "id": alert.id,
                    "location": alert.location,
                    "enabled": alert.is_enabled,
                    "condition": (
                        str(alert.condition) if hasattr(alert, "condition") else None
                    ),
                    "description": (
                        alert.description if hasattr(alert, "description") else None
                    ),
                    "actions": (
                        [str(action) for action in alert.actions]
                        if hasattr(alert, "actions")
                        else []
                    ),
                }
            )

        return json.dumps(
            {
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "alert_count": len(alert_list),
                "alerts": alert_list,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_azure_monitor_alerts", "azure")
    except Exception as e:
        logger.error("failed_to_get_azure_monitor_alerts", error=str(e))
        return json.dumps({"error": str(e), "resource_group": resource_group})


# =============================================================================
# Azure Compute (VMs, AKS, Functions)
# =============================================================================


@function_tool(strict_mode=False)
def describe_azure_vm(
    resource_group: str,
    vm_name: str,
) -> str:
    """
    Get details about an Azure Virtual Machine.

    Args:
        resource_group: Resource group name
        vm_name: VM name

    Returns:
        VM details as JSON string
    """
    try:
        from azure.mgmt.compute import ComputeManagementClient

        credential, subscription_id = _get_azure_credentials()
        compute_client = ComputeManagementClient(credential, subscription_id)

        vm = compute_client.virtual_machines.get(
            resource_group, vm_name, expand="instanceView"
        )

        # Get instance view for status
        instance_view = vm.instance_view
        statuses = []
        if instance_view and instance_view.statuses:
            statuses = [
                {"code": s.code, "level": s.level.value, "message": s.message}
                for s in instance_view.statuses
            ]

        result = {
            "name": vm.name,
            "id": vm.id,
            "location": vm.location,
            "vm_size": vm.hardware_profile.vm_size,
            "os_type": (
                vm.storage_profile.os_disk.os_type.value
                if vm.storage_profile.os_disk.os_type
                else None
            ),
            "provisioning_state": vm.provisioning_state,
            "statuses": statuses,
            "tags": vm.tags or {},
            "zones": vm.zones,
            "network_profile": {
                "network_interfaces": (
                    [ni.id for ni in vm.network_profile.network_interfaces]
                    if vm.network_profile
                    else []
                )
            },
        }

        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "describe_azure_vm", "azure")
    except Exception as e:
        logger.error(
            "failed_to_describe_azure_vm", error=str(e), vm=vm_name, rg=resource_group
        )
        return json.dumps(
            {"error": str(e), "vm_name": vm_name, "resource_group": resource_group}
        )


@function_tool(strict_mode=False)
def list_azure_vms(resource_group: str | None = None) -> str:
    """
    List Azure Virtual Machines.

    Args:
        resource_group: Optional resource group name (lists all VMs if not specified)

    Returns:
        List of VMs as JSON string
    """
    try:
        from azure.mgmt.compute import ComputeManagementClient

        credential, subscription_id = _get_azure_credentials()
        compute_client = ComputeManagementClient(credential, subscription_id)

        if resource_group:
            vms = compute_client.virtual_machines.list(resource_group)
        else:
            vms = compute_client.virtual_machines.list_all()

        vm_list = []
        for vm in vms:
            vm_list.append(
                {
                    "name": vm.name,
                    "id": vm.id,
                    "location": vm.location,
                    "vm_size": vm.hardware_profile.vm_size,
                    "provisioning_state": vm.provisioning_state,
                    "tags": vm.tags or {},
                }
            )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "vm_count": len(vm_list),
                "vms": vm_list,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "list_azure_vms", "azure")
    except Exception as e:
        logger.error("failed_to_list_azure_vms", error=str(e), rg=resource_group)
        return json.dumps({"error": str(e), "resource_group": resource_group})


@function_tool(strict_mode=False)
def describe_aks_cluster(
    resource_group: str,
    cluster_name: str,
) -> str:
    """
    Get details about an Azure Kubernetes Service (AKS) cluster.

    Args:
        resource_group: Resource group name
        cluster_name: AKS cluster name

    Returns:
        AKS cluster details as JSON string
    """
    try:
        from azure.mgmt.containerservice import ContainerServiceClient

        credential, subscription_id = _get_azure_credentials()
        aks_client = ContainerServiceClient(credential, subscription_id)

        cluster = aks_client.managed_clusters.get(resource_group, cluster_name)

        result = {
            "name": cluster.name,
            "id": cluster.id,
            "location": cluster.location,
            "kubernetes_version": cluster.kubernetes_version,
            "provisioning_state": cluster.provisioning_state,
            "fqdn": cluster.fqdn,
            "node_resource_group": cluster.node_resource_group,
            "agent_pools": (
                [
                    {
                        "name": pool.name,
                        "count": pool.count,
                        "vm_size": pool.vm_size,
                        "os_type": pool.os_type.value if pool.os_type else None,
                        "mode": pool.mode.value if pool.mode else None,
                    }
                    for pool in cluster.agent_pool_profiles
                ]
                if cluster.agent_pool_profiles
                else []
            ),
            "network_profile": (
                {
                    "network_plugin": (
                        cluster.network_profile.network_plugin.value
                        if cluster.network_profile
                        and cluster.network_profile.network_plugin
                        else None
                    ),
                    "service_cidr": (
                        cluster.network_profile.service_cidr
                        if cluster.network_profile
                        else None
                    ),
                }
                if cluster.network_profile
                else {}
            ),
            "tags": cluster.tags or {},
        }

        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "describe_aks_cluster", "azure")
    except Exception as e:
        logger.error(
            "failed_to_describe_aks_cluster",
            error=str(e),
            cluster=cluster_name,
            rg=resource_group,
        )
        return json.dumps(
            {
                "error": str(e),
                "cluster_name": cluster_name,
                "resource_group": resource_group,
            }
        )


@function_tool(strict_mode=False)
def list_aks_clusters(resource_group: str | None = None) -> str:
    """
    List AKS clusters.

    Args:
        resource_group: Optional resource group name

    Returns:
        List of AKS clusters as JSON string
    """
    try:
        from azure.mgmt.containerservice import ContainerServiceClient

        credential, subscription_id = _get_azure_credentials()
        aks_client = ContainerServiceClient(credential, subscription_id)

        if resource_group:
            clusters = aks_client.managed_clusters.list_by_resource_group(
                resource_group
            )
        else:
            clusters = aks_client.managed_clusters.list()

        cluster_list = []
        for cluster in clusters:
            cluster_list.append(
                {
                    "name": cluster.name,
                    "id": cluster.id,
                    "location": cluster.location,
                    "kubernetes_version": cluster.kubernetes_version,
                    "provisioning_state": cluster.provisioning_state,
                    "fqdn": cluster.fqdn,
                    "tags": cluster.tags or {},
                }
            )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "cluster_count": len(cluster_list),
                "clusters": cluster_list,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "list_aks_clusters", "azure")
    except Exception as e:
        logger.error("failed_to_list_aks_clusters", error=str(e), rg=resource_group)
        return json.dumps({"error": str(e), "resource_group": resource_group})


@function_tool(strict_mode=False)
def describe_azure_function(
    resource_group: str,
    function_app_name: str,
) -> str:
    """
    Get details about an Azure Function App.

    Args:
        resource_group: Resource group name
        function_app_name: Function App name

    Returns:
        Function App details as JSON string
    """
    try:
        from azure.mgmt.web import WebSiteManagementClient

        credential, subscription_id = _get_azure_credentials()
        web_client = WebSiteManagementClient(credential, subscription_id)

        app = web_client.web_apps.get(resource_group, function_app_name)

        result = {
            "name": app.name,
            "id": app.id,
            "location": app.location,
            "state": app.state,
            "host_names": app.host_names,
            "repository_site_name": app.repository_site_name,
            "usage_state": app.usage_state.value if app.usage_state else None,
            "enabled": app.enabled,
            "enabled_host_names": app.enabled_host_names,
            "availability_state": (
                app.availability_state.value if app.availability_state else None
            ),
            "runtime_version": (
                app.site_config.linux_fx_version if app.site_config else None
            ),
            "tags": app.tags or {},
        }

        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "describe_azure_function", "azure")
    except Exception as e:
        logger.error(
            "failed_to_describe_azure_function",
            error=str(e),
            app=function_app_name,
            rg=resource_group,
        )
        return json.dumps(
            {
                "error": str(e),
                "function_app_name": function_app_name,
                "resource_group": resource_group,
            }
        )


@function_tool(strict_mode=False)
def list_azure_functions(resource_group: str | None = None) -> str:
    """
    List Azure Function Apps.

    Args:
        resource_group: Optional resource group name

    Returns:
        List of Function Apps as JSON string
    """
    try:
        from azure.mgmt.web import WebSiteManagementClient

        credential, subscription_id = _get_azure_credentials()
        web_client = WebSiteManagementClient(credential, subscription_id)

        if resource_group:
            apps = web_client.web_apps.list_by_resource_group(resource_group)
        else:
            apps = web_client.web_apps.list()

        # Filter only Function Apps (kind contains 'functionapp')
        function_apps = []
        for app in apps:
            if app.kind and "functionapp" in app.kind.lower():
                function_apps.append(
                    {
                        "name": app.name,
                        "id": app.id,
                        "location": app.location,
                        "state": app.state,
                        "kind": app.kind,
                        "enabled": app.enabled,
                        "tags": app.tags or {},
                    }
                )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "function_app_count": len(function_apps),
                "function_apps": function_apps,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "list_azure_functions", "azure")
    except Exception as e:
        logger.error("failed_to_list_azure_functions", error=str(e), rg=resource_group)
        return json.dumps({"error": str(e), "resource_group": resource_group})


# =============================================================================
# Azure Databases (SQL, Cosmos DB)
# =============================================================================


@function_tool(strict_mode=False)
def describe_azure_sql_database(
    resource_group: str,
    server_name: str,
    database_name: str,
) -> str:
    """
    Get details about an Azure SQL Database.

    Args:
        resource_group: Resource group name
        server_name: SQL Server name
        database_name: Database name

    Returns:
        Database details as JSON string
    """
    try:
        from azure.mgmt.sql import SqlManagementClient

        credential, subscription_id = _get_azure_credentials()
        sql_client = SqlManagementClient(credential, subscription_id)

        db = sql_client.databases.get(resource_group, server_name, database_name)

        result = {
            "name": db.name,
            "id": db.id,
            "location": db.location,
            "status": db.status.value if db.status else None,
            "sku": (
                {"name": db.sku.name, "tier": db.sku.tier, "capacity": db.sku.capacity}
                if db.sku
                else None
            ),
            "max_size_bytes": db.max_size_bytes,
            "collation": db.collation,
            "creation_date": db.creation_date.isoformat() if db.creation_date else None,
            "earliest_restore_date": (
                db.earliest_restore_date.isoformat()
                if db.earliest_restore_date
                else None
            ),
            "tags": db.tags or {},
        }

        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "describe_azure_sql_database", "azure"
        )
    except Exception as e:
        logger.error(
            "failed_to_describe_azure_sql_db",
            error=str(e),
            db=database_name,
            server=server_name,
        )
        return json.dumps(
            {
                "error": str(e),
                "database_name": database_name,
                "server_name": server_name,
            }
        )


@function_tool(strict_mode=False)
def list_azure_sql_databases(resource_group: str, server_name: str) -> str:
    """
    List Azure SQL Databases on a server.

    Args:
        resource_group: Resource group name
        server_name: SQL Server name

    Returns:
        List of databases as JSON string
    """
    try:
        from azure.mgmt.sql import SqlManagementClient

        credential, subscription_id = _get_azure_credentials()
        sql_client = SqlManagementClient(credential, subscription_id)

        databases = sql_client.databases.list_by_server(resource_group, server_name)

        db_list = []
        for db in databases:
            db_list.append(
                {
                    "name": db.name,
                    "id": db.id,
                    "status": db.status.value if db.status else None,
                    "sku": db.sku.name if db.sku else None,
                    "max_size_bytes": db.max_size_bytes,
                    "creation_date": (
                        db.creation_date.isoformat() if db.creation_date else None
                    ),
                }
            )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "server_name": server_name,
                "database_count": len(db_list),
                "databases": db_list,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "list_azure_sql_databases", "azure")
    except Exception as e:
        logger.error(
            "failed_to_list_azure_sql_databases", error=str(e), server=server_name
        )
        return json.dumps(
            {
                "error": str(e),
                "server_name": server_name,
                "resource_group": resource_group,
            }
        )


@function_tool(strict_mode=False)
def describe_cosmos_db_account(
    resource_group: str,
    account_name: str,
) -> str:
    """
    Get details about an Azure Cosmos DB account.

    Args:
        resource_group: Resource group name
        account_name: Cosmos DB account name

    Returns:
        Cosmos DB account details as JSON string
    """
    try:
        from azure.mgmt.cosmosdb import CosmosDBManagementClient

        credential, subscription_id = _get_azure_credentials()
        cosmos_client = CosmosDBManagementClient(credential, subscription_id)

        account = cosmos_client.database_accounts.get(resource_group, account_name)

        result = {
            "name": account.name,
            "id": account.id,
            "location": account.location,
            "kind": account.kind.value if account.kind else None,
            "provisioning_state": account.provisioning_state,
            "document_endpoint": account.document_endpoint,
            "database_account_offer_type": (
                account.database_account_offer_type.value
                if account.database_account_offer_type
                else None
            ),
            "consistency_policy": (
                {
                    "default_consistency_level": account.consistency_policy.default_consistency_level.value
                }
                if account.consistency_policy
                else None
            ),
            "locations": (
                [
                    {
                        "location_name": loc.location_name,
                        "failover_priority": loc.failover_priority,
                        "is_zone_redundant": loc.is_zone_redundant,
                    }
                    for loc in account.locations
                ]
                if account.locations
                else []
            ),
            "tags": account.tags or {},
        }

        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "describe_cosmos_db_account", "azure"
        )
    except Exception as e:
        logger.error(
            "failed_to_describe_cosmos_db",
            error=str(e),
            account=account_name,
            rg=resource_group,
        )
        return json.dumps(
            {
                "error": str(e),
                "account_name": account_name,
                "resource_group": resource_group,
            }
        )


# =============================================================================
# Azure Cost Management (FinOps - Tim's Focus)
# =============================================================================


@function_tool(strict_mode=False)
def query_azure_cost_management(
    scope: str,
    time_period_start: str,
    time_period_end: str,
    granularity: str = "Monthly",
    group_by: list[str] | None = None,
) -> str:
    """
    Query Azure Cost Management data.

    Args:
        scope: Scope for the query (e.g., "/subscriptions/{subscription-id}")
        time_period_start: Start date in YYYY-MM-DD format
        time_period_end: End date in YYYY-MM-DD format
        granularity: Daily or Monthly
        group_by: Optional list of dimensions to group by (e.g., ["ResourceGroup", "ServiceName"])

    Returns:
        Cost data as JSON string
    """
    try:
        from azure.mgmt.costmanagement import CostManagementClient
        from azure.mgmt.costmanagement.models import (
            QueryAggregation,
            QueryDataset,
            QueryDefinition,
            QueryGrouping,
            QueryTimePeriod,
        )

        credential, subscription_id = _get_azure_credentials()
        cost_client = CostManagementClient(credential)

        # Build query
        dataset = QueryDataset(
            granularity=granularity,
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
        )

        if group_by:
            dataset.grouping = [
                QueryGrouping(type="Dimension", name=dim) for dim in group_by
            ]

        query = QueryDefinition(
            type="Usage",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=time_period_start, to=time_period_end
            ),
            dataset=dataset,
        )

        # Execute query
        if not scope.startswith("/"):
            scope = f"/subscriptions/{subscription_id}"

        result = cost_client.query.usage(scope, query)

        # Parse results
        rows = []
        if result.rows:
            columns = [col.name for col in result.columns]
            for row in result.rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    row_dict[col] = row[i]
                rows.append(row_dict)

        total_cost = sum(float(row.get("Cost", 0)) for row in rows)

        return json.dumps(
            {
                "scope": scope,
                "time_period": {"start": time_period_start, "end": time_period_end},
                "granularity": granularity,
                "total_cost": round(total_cost, 2),
                "currency": "USD",  # Default, adjust if needed
                "row_count": len(rows),
                "rows": rows,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "query_azure_cost_management", "azure"
        )
    except Exception as e:
        logger.error("failed_to_query_cost_management", error=str(e), scope=scope)
        return json.dumps({"error": str(e), "scope": scope})


@function_tool(strict_mode=False)
def get_azure_advisor_recommendations(
    resource_group: str | None = None, category: str | None = None
) -> str:
    """
    Get Azure Advisor recommendations (cost optimization, security, reliability, performance).

    Args:
        resource_group: Optional resource group to filter
        category: Optional category filter (Cost, Security, Reliability, Performance, OperationalExcellence)

    Returns:
        Advisor recommendations as JSON string
    """
    try:
        from azure.mgmt.advisor import AdvisorManagementClient

        credential, subscription_id = _get_azure_credentials()
        advisor_client = AdvisorManagementClient(credential, subscription_id)

        # Get recommendations
        recommendations = advisor_client.recommendations.list()

        rec_list = []
        for rec in recommendations:
            # Filter by category if specified
            if category and rec.category.lower() != category.lower():
                continue

            # Filter by resource group if specified
            if resource_group and resource_group not in rec.id:
                continue

            rec_list.append(
                {
                    "name": rec.name,
                    "id": rec.id,
                    "category": rec.category,
                    "impact": rec.impact,
                    "risk": rec.risk if hasattr(rec, "risk") else None,
                    "short_description": (
                        rec.short_description.problem if rec.short_description else None
                    ),
                    "solution": (
                        rec.short_description.solution
                        if rec.short_description
                        else None
                    ),
                    "impacted_value": (
                        rec.impacted_value if hasattr(rec, "impacted_value") else None
                    ),
                    "potential_benefits": (
                        rec.extended_properties.get("annualSavingsAmount")
                        if rec.extended_properties
                        else None
                    ),
                }
            )

        # Calculate total potential savings
        total_savings = 0
        for rec in rec_list:
            if rec.get("potential_benefits"):
                try:
                    total_savings += float(rec["potential_benefits"])
                except:
                    pass

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "category_filter": category,
                "recommendation_count": len(rec_list),
                "potential_annual_savings": (
                    round(total_savings, 2) if total_savings > 0 else None
                ),
                "recommendations": rec_list,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "get_azure_advisor_recommendations", "azure"
        )
    except Exception as e:
        logger.error("failed_to_get_advisor_recommendations", error=str(e))
        return json.dumps(
            {"error": str(e), "resource_group": resource_group, "category": category}
        )


# =============================================================================
# Azure Backup and Site Recovery (BCDR - Tim's Focus)
# =============================================================================


@function_tool(strict_mode=False)
def list_azure_backup_vaults(resource_group: str | None = None) -> str:
    """
    List Azure Recovery Services vaults (used for backup and site recovery).

    Args:
        resource_group: Optional resource group name

    Returns:
        List of backup vaults as JSON string
    """
    try:
        from azure.mgmt.recoveryservices import RecoveryServicesClient

        credential, subscription_id = _get_azure_credentials()
        rs_client = RecoveryServicesClient(credential, subscription_id)

        if resource_group:
            vaults = rs_client.vaults.list_by_resource_group(resource_group)
        else:
            vaults = rs_client.vaults.list_by_subscription_id()

        vault_list = []
        for vault in vaults:
            vault_list.append(
                {
                    "name": vault.name,
                    "id": vault.id,
                    "location": vault.location,
                    "sku": vault.sku.name.value if vault.sku else None,
                    "properties": {
                        "provisioning_state": (
                            vault.properties.provisioning_state
                            if vault.properties
                            else None
                        )
                    },
                    "tags": vault.tags or {},
                }
            )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "vault_count": len(vault_list),
                "vaults": vault_list,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "list_azure_backup_vaults", "azure")
    except Exception as e:
        logger.error("failed_to_list_backup_vaults", error=str(e), rg=resource_group)
        return json.dumps({"error": str(e), "resource_group": resource_group})


@function_tool(strict_mode=False)
def get_azure_backup_status(
    resource_group: str,
    vault_name: str,
) -> str:
    """
    Get backup status and protected items in a Recovery Services vault.

    Args:
        resource_group: Resource group name
        vault_name: Recovery Services vault name

    Returns:
        Backup status as JSON string
    """
    try:
        from azure.mgmt.recoveryservicesbackup import RecoveryServicesBackupClient

        credential, subscription_id = _get_azure_credentials()
        backup_client = RecoveryServicesBackupClient(credential, subscription_id)

        # Get protected items
        protected_items = backup_client.backup_protected_items.list(
            vault_name, resource_group
        )

        items = []
        for item in protected_items:
            items.append(
                {
                    "name": item.name,
                    "id": item.id,
                    "friendly_name": (
                        item.properties.friendly_name if item.properties else None
                    ),
                    "backup_management_type": (
                        item.properties.backup_management_type
                        if item.properties
                        else None
                    ),
                    "workload_type": (
                        item.properties.workload_type if item.properties else None
                    ),
                    "protection_state": (
                        item.properties.protection_state if item.properties else None
                    ),
                    "health_status": (
                        item.properties.health_status if item.properties else None
                    ),
                    "last_backup_time": (
                        item.properties.last_backup_time.isoformat()
                        if item.properties
                        and hasattr(item.properties, "last_backup_time")
                        and item.properties.last_backup_time
                        else None
                    ),
                }
            )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "vault_name": vault_name,
                "protected_item_count": len(items),
                "protected_items": items,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_azure_backup_status", "azure")
    except Exception as e:
        logger.error(
            "failed_to_get_backup_status",
            error=str(e),
            vault=vault_name,
            rg=resource_group,
        )
        return json.dumps(
            {
                "error": str(e),
                "vault_name": vault_name,
                "resource_group": resource_group,
            }
        )


# =============================================================================
# Azure Networking
# =============================================================================


@function_tool(strict_mode=False)
def describe_azure_vnet(
    resource_group: str,
    vnet_name: str,
) -> str:
    """
    Get details about an Azure Virtual Network.

    Args:
        resource_group: Resource group name
        vnet_name: Virtual network name

    Returns:
        VNet details as JSON string
    """
    try:
        from azure.mgmt.network import NetworkManagementClient

        credential, subscription_id = _get_azure_credentials()
        network_client = NetworkManagementClient(credential, subscription_id)

        vnet = network_client.virtual_networks.get(resource_group, vnet_name)

        result = {
            "name": vnet.name,
            "id": vnet.id,
            "location": vnet.location,
            "provisioning_state": vnet.provisioning_state,
            "address_space": (
                {"address_prefixes": vnet.address_space.address_prefixes}
                if vnet.address_space
                else None
            ),
            "subnets": (
                [
                    {
                        "name": subnet.name,
                        "address_prefix": subnet.address_prefix,
                        "provisioning_state": subnet.provisioning_state,
                    }
                    for subnet in vnet.subnets
                ]
                if vnet.subnets
                else []
            ),
            "tags": vnet.tags or {},
        }

        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "describe_azure_vnet", "azure")
    except Exception as e:
        logger.error(
            "failed_to_describe_vnet", error=str(e), vnet=vnet_name, rg=resource_group
        )
        return json.dumps(
            {"error": str(e), "vnet_name": vnet_name, "resource_group": resource_group}
        )


@function_tool(strict_mode=False)
def get_azure_nsg_rules(
    resource_group: str,
    nsg_name: str,
) -> str:
    """
    Get Network Security Group (NSG) rules.

    Args:
        resource_group: Resource group name
        nsg_name: NSG name

    Returns:
        NSG rules as JSON string
    """
    try:
        from azure.mgmt.network import NetworkManagementClient

        credential, subscription_id = _get_azure_credentials()
        network_client = NetworkManagementClient(credential, subscription_id)

        nsg = network_client.network_security_groups.get(resource_group, nsg_name)

        rules = []
        if nsg.security_rules:
            for rule in nsg.security_rules:
                rules.append(
                    {
                        "name": rule.name,
                        "priority": rule.priority,
                        "direction": rule.direction,
                        "access": rule.access,
                        "protocol": rule.protocol,
                        "source_address_prefix": rule.source_address_prefix,
                        "source_port_range": rule.source_port_range,
                        "destination_address_prefix": rule.destination_address_prefix,
                        "destination_port_range": rule.destination_port_range,
                        "description": rule.description,
                    }
                )

        return json.dumps(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "nsg_name": nsg_name,
                "rule_count": len(rules),
                "rules": rules,
            }
        )

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_azure_nsg_rules", "azure")
    except Exception as e:
        logger.error(
            "failed_to_get_nsg_rules", error=str(e), nsg=nsg_name, rg=resource_group
        )
        return json.dumps(
            {"error": str(e), "nsg_name": nsg_name, "resource_group": resource_group}
        )
