"""Google Cloud Platform (GCP) infrastructure access tools."""

import json
import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_gcp_config() -> dict:
    """Get GCP configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("gcp")
        if config and config.get("service_account_key") and config.get("project_id"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("GCP_SERVICE_ACCOUNT_KEY") and os.getenv("GCP_PROJECT_ID"):
        return {
            "service_account_key": os.getenv("GCP_SERVICE_ACCOUNT_KEY"),
            "project_id": os.getenv("GCP_PROJECT_ID"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="gcp",
        tool_id="gcp_tools",
        missing_fields=["service_account_key", "project_id"],
    )


def _get_gcp_credentials():
    """Get GCP service account credentials."""
    try:
        from google.oauth2 import service_account

        config = _get_gcp_config()

        # Parse service account key JSON
        credentials_dict = json.loads(config["service_account_key"])
        return service_account.Credentials.from_service_account_info(credentials_dict)

    except ImportError:
        raise ToolExecutionError(
            "gcp", "google-auth not installed. Install with: pip install google-auth"
        )


def gcp_list_compute_instances(zone: str | None = None) -> list[dict[str, Any]]:
    """
    List Compute Engine VM instances.

    Args:
        zone: Optional zone filter (e.g., "us-central1-a")

    Returns:
        List of VM instances
    """
    try:
        from googleapiclient import discovery

        config = _get_gcp_config()
        credentials = _get_gcp_credentials()

        compute = discovery.build("compute", "v1", credentials=credentials)

        instances = []

        if zone:
            # List instances in specific zone
            result = (
                compute.instances()
                .list(project=config["project_id"], zone=zone)
                .execute()
            )

            for instance in result.get("items", []):
                instances.append(
                    {
                        "name": instance["name"],
                        "zone": zone,
                        "machine_type": instance["machineType"].split("/")[-1],
                        "status": instance["status"],
                        "internal_ip": (
                            instance["networkInterfaces"][0].get("networkIP")
                            if instance.get("networkInterfaces")
                            else None
                        ),
                        "external_ip": (
                            instance["networkInterfaces"][0]
                            .get("accessConfigs", [{}])[0]
                            .get("natIP")
                            if instance.get("networkInterfaces")
                            else None
                        ),
                    }
                )
        else:
            # List instances in all zones
            zones_result = compute.zones().list(project=config["project_id"]).execute()

            for zone_data in zones_result.get("items", []):
                zone_name = zone_data["name"]
                result = (
                    compute.instances()
                    .list(project=config["project_id"], zone=zone_name)
                    .execute()
                )

                for instance in result.get("items", []):
                    instances.append(
                        {
                            "name": instance["name"],
                            "zone": zone_name,
                            "machine_type": instance["machineType"].split("/")[-1],
                            "status": instance["status"],
                            "internal_ip": (
                                instance["networkInterfaces"][0].get("networkIP")
                                if instance.get("networkInterfaces")
                                else None
                            ),
                            "external_ip": (
                                instance["networkInterfaces"][0]
                                .get("accessConfigs", [{}])[0]
                                .get("natIP")
                                if instance.get("networkInterfaces")
                                else None
                            ),
                        }
                    )

        logger.info("gcp_instances_listed", count=len(instances), zone=zone or "all")
        return instances

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gcp_list_compute_instances", "gcp")
    except Exception as e:
        logger.error("gcp_list_instances_failed", error=str(e), zone=zone)
        raise ToolExecutionError("gcp_list_compute_instances", str(e), e)


def gcp_list_gke_clusters() -> list[dict[str, Any]]:
    """
    List Google Kubernetes Engine (GKE) clusters.

    Returns:
        List of GKE clusters
    """
    try:
        from googleapiclient import discovery

        config = _get_gcp_config()
        credentials = _get_gcp_credentials()

        container = discovery.build("container", "v1", credentials=credentials)

        parent = f"projects/{config['project_id']}/locations/-"
        result = (
            container.projects().locations().clusters().list(parent=parent).execute()
        )

        clusters = []
        for cluster in result.get("clusters", []):
            clusters.append(
                {
                    "name": cluster["name"],
                    "location": cluster["location"],
                    "status": cluster["status"],
                    "current_master_version": cluster.get("currentMasterVersion"),
                    "current_node_version": cluster.get("currentNodeVersion"),
                    "current_node_count": cluster.get("currentNodeCount"),
                    "endpoint": cluster.get("endpoint"),
                }
            )

        logger.info("gcp_gke_clusters_listed", count=len(clusters))
        return clusters

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gcp_list_gke_clusters", "gcp")
    except Exception as e:
        logger.error("gcp_list_gke_clusters_failed", error=str(e))
        raise ToolExecutionError("gcp_list_gke_clusters", str(e), e)


def gcp_list_cloud_functions() -> list[dict[str, Any]]:
    """
    List Cloud Functions.

    Returns:
        List of Cloud Functions
    """
    try:
        from googleapiclient import discovery

        config = _get_gcp_config()
        credentials = _get_gcp_credentials()

        functions = discovery.build("cloudfunctions", "v1", credentials=credentials)

        parent = f"projects/{config['project_id']}/locations/-"
        result = (
            functions.projects().locations().functions().list(parent=parent).execute()
        )

        function_list = []
        for function in result.get("functions", []):
            function_list.append(
                {
                    "name": function["name"].split("/")[-1],
                    "runtime": function.get("runtime"),
                    "status": function.get("status"),
                    "entry_point": function.get("entryPoint"),
                    "https_trigger": function.get("httpsTrigger", {}).get("url"),
                    "update_time": function.get("updateTime"),
                }
            )

        logger.info("gcp_cloud_functions_listed", count=len(function_list))
        return function_list

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gcp_list_cloud_functions", "gcp")
    except Exception as e:
        logger.error("gcp_list_cloud_functions_failed", error=str(e))
        raise ToolExecutionError("gcp_list_cloud_functions", str(e), e)


def gcp_list_cloud_sql_instances() -> list[dict[str, Any]]:
    """
    List Cloud SQL database instances.

    Returns:
        List of Cloud SQL instances
    """
    try:
        from googleapiclient import discovery

        config = _get_gcp_config()
        credentials = _get_gcp_credentials()

        sqladmin = discovery.build("sqladmin", "v1beta4", credentials=credentials)

        result = sqladmin.instances().list(project=config["project_id"]).execute()

        instances = []
        for instance in result.get("items", []):
            instances.append(
                {
                    "name": instance["name"],
                    "database_version": instance.get("databaseVersion"),
                    "state": instance.get("state"),
                    "region": instance.get("region"),
                    "tier": instance["settings"].get("tier"),
                    "ip_addresses": [
                        ip["ipAddress"] for ip in instance.get("ipAddresses", [])
                    ],
                }
            )

        logger.info("gcp_cloud_sql_instances_listed", count=len(instances))
        return instances

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "gcp_list_cloud_sql_instances", "gcp"
        )
    except Exception as e:
        logger.error("gcp_list_cloud_sql_failed", error=str(e))
        raise ToolExecutionError("gcp_list_cloud_sql_instances", str(e), e)


def gcp_get_project_metadata() -> dict[str, Any]:
    """
    Get GCP project metadata and information.

    Returns:
        Project metadata
    """
    try:
        from googleapiclient import discovery

        config = _get_gcp_config()
        credentials = _get_gcp_credentials()

        cloudresourcemanager = discovery.build(
            "cloudresourcemanager", "v1", credentials=credentials
        )

        project = (
            cloudresourcemanager.projects()
            .get(projectId=config["project_id"])
            .execute()
        )

        logger.info("gcp_project_metadata_retrieved", project_id=config["project_id"])

        return {
            "project_id": project["projectId"],
            "project_number": project["projectNumber"],
            "name": project.get("name"),
            "lifecycle_state": project.get("lifecycleState"),
            "create_time": project.get("createTime"),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "gcp_get_project_metadata", "gcp")
    except Exception as e:
        logger.error("gcp_get_project_metadata_failed", error=str(e))
        raise ToolExecutionError("gcp_get_project_metadata", str(e), e)


# List of all GCP tools for registration
GCP_TOOLS = [
    gcp_list_compute_instances,
    gcp_list_gke_clusters,
    gcp_list_cloud_functions,
    gcp_list_cloud_sql_instances,
    gcp_get_project_metadata,
]
