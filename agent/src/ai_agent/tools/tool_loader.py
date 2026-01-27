"""
Dynamic tool loader based on available integrations.

Loads tools conditionally based on:
1. Whether the integration library is installed
2. Whether credentials are configured
3. Team configuration (MCP servers, enabled tools)
"""

import importlib
import os
from collections.abc import Callable
from typing import Any

from ..core.config import get_config
from ..core.logging import get_logger

logger = get_logger(__name__)


def is_integration_available(module_name: str) -> bool:
    """Check if an integration module is available."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def load_tools_for_agent(agent_name: str) -> list[Callable]:
    """
    Load all available tools for an agent.

    Args:
        agent_name: Name of the agent

    Returns:
        List of tool functions
    """
    tools = []
    config = get_config()

    # Always available tools
    from .thinking import think

    tools.append(think)

    # K8s tools (if kubernetes library available)
    if is_integration_available("kubernetes"):
        try:
            from .kubernetes import (
                describe_deployment,
                describe_pod,
                describe_service,
                get_deployment_history,
                get_pod_events,
                get_pod_logs,
                get_pod_resource_usage,
                get_pod_resources,
                list_namespaces,
                list_pods,
            )

            tools.extend(
                [
                    get_pod_logs,
                    describe_pod,
                    list_pods,
                    list_namespaces,
                    get_pod_events,
                    describe_deployment,
                    get_deployment_history,
                    describe_service,
                    get_pod_resource_usage,
                    get_pod_resources,
                ]
            )
            logger.debug("k8s_tools_loaded", count=10)
        except Exception as e:
            logger.warning("k8s_tools_load_failed", error=str(e))

    # AWS tools (always available - boto3 is core dependency)
    from .aws_tools import (
        describe_ec2_instance,
        describe_lambda_function,
        get_cloudwatch_logs,
        get_cloudwatch_metrics,
        get_rds_instance_status,
        list_ecs_tasks,
        query_cloudwatch_insights,
    )

    tools.extend(
        [
            describe_ec2_instance,
            get_cloudwatch_logs,
            describe_lambda_function,
            get_rds_instance_status,
            query_cloudwatch_insights,
            get_cloudwatch_metrics,
            list_ecs_tasks,
        ]
    )
    logger.debug("aws_tools_loaded", count=7)

    # Azure tools (if azure-identity and azure-mgmt available)
    if is_integration_available("azure.identity") and is_integration_available(
        "azure.mgmt.compute"
    ):
        try:
            from .azure_tools import (
                describe_aks_cluster,
                describe_azure_function,
                describe_azure_sql_database,
                describe_azure_vm,
                describe_azure_vnet,
                describe_cosmos_db_account,
                get_application_insights_traces,
                get_azure_advisor_recommendations,
                get_azure_backup_status,
                get_azure_monitor_alerts,
                get_azure_monitor_metrics,
                get_azure_nsg_rules,
                list_aks_clusters,
                list_azure_backup_vaults,
                list_azure_functions,
                list_azure_sql_databases,
                list_azure_vms,
                query_azure_cost_management,
                query_azure_resource_graph,
                query_log_analytics,
            )

            tools.extend(
                [
                    query_log_analytics,
                    query_azure_resource_graph,
                    get_application_insights_traces,
                    get_azure_monitor_metrics,
                    get_azure_monitor_alerts,
                    describe_azure_vm,
                    list_azure_vms,
                    describe_aks_cluster,
                    list_aks_clusters,
                    describe_azure_function,
                    list_azure_functions,
                    describe_azure_sql_database,
                    list_azure_sql_databases,
                    describe_cosmos_db_account,
                    query_azure_cost_management,
                    get_azure_advisor_recommendations,
                    list_azure_backup_vaults,
                    get_azure_backup_status,
                    describe_azure_vnet,
                    get_azure_nsg_rules,
                ]
            )
            logger.debug("azure_tools_loaded", count=20)
        except Exception as e:
            logger.warning("azure_tools_load_failed", error=str(e))

    # Slack tools (if slack-sdk available)
    if is_integration_available("slack_sdk"):
        try:
            from .slack_tools import (
                get_channel_history,
                get_thread_replies,
                post_slack_message,
                search_slack_messages,
            )

            tools.extend(
                [
                    search_slack_messages,
                    get_channel_history,
                    get_thread_replies,
                    post_slack_message,
                ]
            )
            logger.debug("slack_tools_loaded", count=4)
        except Exception as e:
            logger.warning("slack_tools_load_failed", error=str(e))

    # GitHub tools (if PyGithub available)
    if is_integration_available("github"):
        try:
            from .github_tools import (
                close_issue,
                create_branch,
                create_issue,
                create_pull_request,
                get_check_runs,
                get_combined_status,
                get_deployment_status,
                get_failed_workflow_annotations,
                get_repo_info,
                get_repo_tree,
                get_workflow_run_jobs,
                get_workflow_run_logs,
                list_branches,
                list_deployments,
                list_files,
                list_issues,
                list_pull_requests,
                list_workflow_runs,
                merge_pull_request,
                read_github_file,
                search_github_code,
                trigger_workflow,
            )

            tools.extend(
                [
                    search_github_code,
                    read_github_file,
                    create_pull_request,
                    list_pull_requests,
                    merge_pull_request,
                    create_issue,
                    list_issues,
                    close_issue,
                    create_branch,
                    list_branches,
                    list_files,
                    get_repo_info,
                    trigger_workflow,
                    list_workflow_runs,
                    # New tools for CI/CD and deployment investigation
                    get_repo_tree,
                    get_workflow_run_jobs,
                    get_workflow_run_logs,
                    get_failed_workflow_annotations,
                    get_check_runs,
                    get_combined_status,
                    list_deployments,
                    get_deployment_status,
                ]
            )
            logger.debug("github_tools_loaded", count=22)
        except Exception as e:
            logger.warning("github_tools_load_failed", error=str(e))

    # Elasticsearch tools (if elasticsearch available)
    if is_integration_available("elasticsearch"):
        try:
            from .elasticsearch_tools import (
                aggregate_errors_by_field,
                search_logs,
            )

            tools.extend(
                [
                    search_logs,
                    aggregate_errors_by_field,
                ]
            )
            logger.debug("elasticsearch_tools_loaded", count=2)
        except Exception as e:
            logger.warning("elasticsearch_tools_load_failed", error=str(e))

    # Confluence tools (if atlassian available)
    if is_integration_available("atlassian"):
        try:
            from .confluence_tools import (
                get_confluence_page,
                list_space_pages,
                search_confluence,
            )

            tools.extend(
                [
                    search_confluence,
                    get_confluence_page,
                    list_space_pages,
                ]
            )
            logger.debug("confluence_tools_loaded", count=3)
        except Exception as e:
            logger.warning("confluence_tools_load_failed", error=str(e))

    # Sourcegraph tools
    if is_integration_available("httpx"):
        try:
            from .sourcegraph_tools import search_sourcegraph

            tools.append(search_sourcegraph)
            logger.debug("sourcegraph_tools_loaded", count=1)
        except Exception as e:
            logger.warning("sourcegraph_tools_load_failed", error=str(e))

    # Datadog tools (if datadog-api-client available)
    if is_integration_available("datadog_api_client"):
        try:
            from .datadog_tools import (
                get_service_apm_metrics,
                query_datadog_metrics,
                search_datadog_logs,
            )

            tools.extend(
                [
                    query_datadog_metrics,
                    search_datadog_logs,
                    get_service_apm_metrics,
                ]
            )
            logger.debug("datadog_tools_loaded", count=3)
        except Exception as e:
            logger.warning("datadog_tools_load_failed", error=str(e))

    # New Relic tools
    if is_integration_available("httpx"):
        try:
            from .newrelic_tools import (
                get_apm_summary,
                query_newrelic_nrql,
            )

            tools.extend(
                [
                    query_newrelic_nrql,
                    get_apm_summary,
                ]
            )
            logger.debug("newrelic_tools_loaded", count=2)
        except Exception as e:
            logger.warning("newrelic_tools_load_failed", error=str(e))

    # Google Docs tools
    if is_integration_available("googleapiclient"):
        try:
            from .google_docs_tools import (
                list_folder_contents,
                read_google_doc,
                search_google_drive,
            )

            tools.extend(
                [
                    read_google_doc,
                    search_google_drive,
                    list_folder_contents,
                ]
            )
            logger.debug("google_tools_loaded", count=3)
        except Exception as e:
            logger.warning("google_tools_load_failed", error=str(e))

    # Git tools (always available - wraps git CLI)
    try:
        from .git_tools import (
            git_blame,
            git_branch_list,
            git_diff,
            git_log,
            git_show,
            git_status,
        )

        tools.extend(
            [
                git_status,
                git_diff,
                git_log,
                git_blame,
                git_show,
                git_branch_list,
            ]
        )
        logger.debug("git_tools_loaded", count=6)
    except Exception as e:
        logger.warning("git_tools_load_failed", error=str(e))

    # Docker tools (always available - wraps docker CLI)
    try:
        from .docker_tools import (
            docker_compose_logs,
            docker_compose_ps,
            docker_exec,
            docker_images,
            docker_inspect,
            docker_logs,
            docker_ps,
            docker_stats,
        )

        tools.extend(
            [
                docker_ps,
                docker_logs,
                docker_inspect,
                docker_exec,
                docker_images,
                docker_stats,
                docker_compose_ps,
                docker_compose_logs,
            ]
        )
        logger.debug("docker_tools_loaded", count=8)
    except Exception as e:
        logger.warning("docker_tools_load_failed", error=str(e))

    # Coding tools (always available)
    try:
        from .coding_tools import (
            list_directory,
            pytest_run,
            python_run_tests,
            read_file,
            repo_search_text,
            run_linter,
            write_file,
        )

        tools.extend(
            [
                repo_search_text,
                python_run_tests,
                pytest_run,
                read_file,
                write_file,
                list_directory,
                run_linter,
            ]
        )
        logger.debug("coding_tools_loaded", count=7)
    except Exception as e:
        logger.warning("coding_tools_load_failed", error=str(e))

    # Browser tools (requires playwright)
    if is_integration_available("playwright"):
        try:
            from .browser_tools import (
                browser_fetch_html,
                browser_pdf,
                browser_scrape,
                browser_screenshot,
            )

            tools.extend(
                [
                    browser_screenshot,
                    browser_scrape,
                    browser_fetch_html,
                    browser_pdf,
                ]
            )
            logger.debug("browser_tools_loaded", count=4)
        except Exception as e:
            logger.warning("browser_tools_load_failed", error=str(e))

    # Package tools (always available - wraps package manager CLIs)
    try:
        from .package_tools import (
            check_tool_available,
            npm_install,
            npm_run,
            pip_freeze,
            pip_install,
            pip_list,
            poetry_install,
            venv_create,
            yarn_install,
        )

        tools.extend(
            [
                pip_install,
                pip_list,
                pip_freeze,
                npm_install,
                npm_run,
                yarn_install,
                poetry_install,
                venv_create,
                check_tool_available,
            ]
        )
        logger.debug("package_tools_loaded", count=9)
    except Exception as e:
        logger.warning("package_tools_load_failed", error=str(e))

    # Anomaly detection tools (always available - pure Python)
    try:
        from .anomaly_tools import (
            analyze_metric_distribution,
            correlate_metrics,
            detect_anomalies,
            find_change_point,
            forecast_metric,
        )

        tools.extend(
            [
                detect_anomalies,
                correlate_metrics,
                find_change_point,
                forecast_metric,
                analyze_metric_distribution,
            ]
        )
        logger.debug("anomaly_tools_loaded", count=5)
    except Exception as e:
        logger.warning("anomaly_tools_load_failed", error=str(e))

    # Prophet-based anomaly detection (if prophet available)
    if is_integration_available("prophet"):
        try:
            from .anomaly_tools import (
                prophet_decompose,
                prophet_detect_anomalies,
                prophet_forecast,
            )

            tools.extend(
                [
                    prophet_detect_anomalies,
                    prophet_forecast,
                    prophet_decompose,
                ]
            )
            logger.debug("prophet_tools_loaded", count=3)
        except Exception as e:
            logger.warning("prophet_tools_load_failed", error=str(e))

    # Grafana tools (if httpx available and configured)
    if is_integration_available("httpx"):
        try:
            from .grafana_tools import (
                grafana_get_alerts,
                grafana_get_annotations,
                grafana_get_dashboard,
                grafana_list_dashboards,
                grafana_list_datasources,
                grafana_query_prometheus,
            )

            tools.extend(
                [
                    grafana_list_dashboards,
                    grafana_get_dashboard,
                    grafana_query_prometheus,
                    grafana_list_datasources,
                    grafana_get_annotations,
                    grafana_get_alerts,
                ]
            )
            logger.debug("grafana_tools_loaded", count=6)
        except Exception as e:
            logger.warning("grafana_tools_load_failed", error=str(e))

    # Knowledge Base tools (RAPTOR) - only if RAPTOR_ENABLED=true
    raptor_enabled = os.getenv("RAPTOR_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    if raptor_enabled and is_integration_available("httpx"):
        try:
            from .knowledge_base_tools import (
                ask_knowledge_base,
                find_similar_past_incidents,
                get_knowledge_context,
                list_knowledge_trees,
                query_service_graph,
                # Enhanced RAG tools (ultimate_rag integration)
                search_for_incident,
                search_knowledge_base,
                teach_knowledge_base,
            )

            tools.extend(
                [
                    # Basic RAPTOR tools
                    search_knowledge_base,
                    ask_knowledge_base,
                    get_knowledge_context,
                    list_knowledge_trees,
                    # Enhanced RAG tools for incident investigation
                    search_for_incident,  # Incident-aware search
                    query_service_graph,  # Service dependency graph queries
                    teach_knowledge_base,  # Agents can teach KB new knowledge
                    find_similar_past_incidents,  # Find similar past incidents
                ]
            )
            logger.debug("knowledge_base_tools_loaded", count=8)
        except Exception as e:
            logger.warning("knowledge_base_tools_load_failed", error=str(e))
    elif not raptor_enabled:
        logger.debug("knowledge_base_tools_skipped", reason="RAPTOR_ENABLED not set")

    # Remediation tools - for proposing fixes with approval
    if is_integration_available("httpx"):
        try:
            from .remediation_tools import (
                get_current_replicas,
                get_remediation_status,
                list_pending_remediations,
                propose_deployment_restart,
                propose_deployment_rollback,
                propose_emergency_action,
                propose_pod_restart,
                propose_remediation,
                propose_scale_deployment,
            )

            tools.extend(
                [
                    propose_remediation,
                    propose_pod_restart,
                    propose_deployment_restart,
                    propose_scale_deployment,
                    propose_deployment_rollback,
                    propose_emergency_action,
                    get_current_replicas,
                    list_pending_remediations,
                    get_remediation_status,
                ]
            )
            logger.debug("remediation_tools_loaded", count=9)
        except Exception as e:
            logger.warning("remediation_tools_load_failed", error=str(e))

    # Snowflake tools (if snowflake-connector-python available)
    if is_integration_available("snowflake.connector"):
        try:
            from .snowflake_tools import (
                get_customer_info,
                get_deployment_incidents,
                get_incident_customer_impact,
                get_incident_timeline,
                get_recent_incidents,
                get_snowflake_schema,
                run_snowflake_query,
                search_incidents_by_service,
                snowflake_bulk_export,
                snowflake_describe_table,
                snowflake_list_tables,
            )

            tools.extend(
                [
                    get_snowflake_schema,
                    run_snowflake_query,
                    get_recent_incidents,
                    get_incident_customer_impact,
                    get_deployment_incidents,
                    get_customer_info,
                    get_incident_timeline,
                    search_incidents_by_service,
                    snowflake_list_tables,
                    snowflake_describe_table,
                    snowflake_bulk_export,
                ]
            )
            logger.debug("snowflake_tools_loaded", count=11)
        except Exception as e:
            logger.warning("snowflake_tools_load_failed", error=str(e))

    # PostgreSQL tools (if psycopg2 available) - works with RDS, Aurora, etc.
    if is_integration_available("psycopg2"):
        try:
            from .postgres_tools import (
                postgres_describe_table,
                postgres_execute_query,
                postgres_list_tables,
            )

            tools.extend(
                [
                    postgres_list_tables,
                    postgres_describe_table,
                    postgres_execute_query,
                ]
            )
            logger.debug("postgres_tools_loaded", count=3)
        except Exception as e:
            logger.warning("postgres_tools_load_failed", error=str(e))

    # BigQuery tools (if google-cloud-bigquery available)
    if is_integration_available("google.cloud.bigquery"):
        try:
            from .bigquery_tools import (
                bigquery_get_table_schema,
                bigquery_list_datasets,
                bigquery_list_tables,
                bigquery_query,
            )

            tools.extend(
                [
                    bigquery_query,
                    bigquery_list_datasets,
                    bigquery_list_tables,
                    bigquery_get_table_schema,
                ]
            )
            logger.debug("bigquery_tools_loaded", count=4)
        except Exception as e:
            logger.warning("bigquery_tools_load_failed", error=str(e))

    # Coralogix tools (if httpx available - already a dependency)
    if is_integration_available("httpx"):
        try:
            from .coralogix_tools import (
                get_coralogix_alerts,
                get_coralogix_error_logs,
                get_coralogix_service_health,
                list_coralogix_services,
                query_coralogix_metrics,
                search_coralogix_logs,
                search_coralogix_traces,
            )

            tools.extend(
                [
                    search_coralogix_logs,
                    get_coralogix_error_logs,
                    get_coralogix_alerts,
                    query_coralogix_metrics,
                    search_coralogix_traces,
                    get_coralogix_service_health,
                    list_coralogix_services,
                ]
            )
            logger.debug("coralogix_tools_loaded", count=7)
        except Exception as e:
            logger.warning("coralogix_tools_load_failed", error=str(e))

    # Log Analysis tools (partition-first log investigation)
    # These tools work across multiple backends (ES, Coralogix, Datadog, Splunk, CloudWatch)
    try:
        from .log_analysis_tools import (
            correlate_logs_with_events,
            detect_log_anomalies,
            extract_log_signatures,
            get_log_statistics,
            get_logs_around_timestamp,
            sample_logs,
            search_logs_by_pattern,
        )

        tools.extend(
            [
                get_log_statistics,
                sample_logs,
                search_logs_by_pattern,
                get_logs_around_timestamp,
                correlate_logs_with_events,
                extract_log_signatures,
                detect_log_anomalies,
            ]
        )
        logger.debug("log_analysis_tools_loaded", count=7)
    except Exception as e:
        logger.warning("log_analysis_tools_load_failed", error=str(e))

    # Service Dependency tools - query pre-discovered dependencies from DB
    # Requires sqlalchemy (core dependency)
    if is_integration_available("sqlalchemy"):
        try:
            from .dependency_tools import (
                get_blast_radius,
                get_dependency_graph_stats,
                get_service_dependencies,
                get_service_dependents,
            )

            tools.extend(
                [
                    get_service_dependencies,
                    get_service_dependents,
                    get_blast_radius,
                    get_dependency_graph_stats,
                ]
            )
            logger.debug("dependency_tools_loaded", count=4)
        except Exception as e:
            logger.warning("dependency_tools_load_failed", error=str(e))

    # Meeting transcription tools (Fireflies, Circleback, Vexa, Otter)
    # Requires httpx (already a core dependency)
    if is_integration_available("httpx"):
        try:
            from .meeting_tools import (
                meeting_get_recent,
                meeting_get_transcript,
                meeting_join,
                meeting_search,
                meeting_search_transcript,
            )

            tools.extend(
                [
                    meeting_search,
                    meeting_get_transcript,
                    meeting_get_recent,
                    meeting_search_transcript,
                    meeting_join,
                ]
            )
            logger.debug("meeting_tools_loaded", count=5)
        except Exception as e:
            logger.warning("meeting_tools_load_failed", error=str(e))

    # PagerDuty tools (uses requests - core dependency)
    try:
        from .pagerduty_tools import (
            pagerduty_calculate_mttr,
            pagerduty_get_escalation_policy,
            pagerduty_get_incident,
            pagerduty_get_incident_log_entries,
            pagerduty_list_incidents,
        )

        tools.extend(
            [
                pagerduty_get_incident,
                pagerduty_get_incident_log_entries,
                pagerduty_list_incidents,
                pagerduty_get_escalation_policy,
                pagerduty_calculate_mttr,
            ]
        )
        logger.debug("pagerduty_tools_loaded", count=5)
    except Exception as e:
        logger.warning("pagerduty_tools_load_failed", error=str(e))

    # Sentry tools (uses requests - core dependency)
    try:
        from .sentry_tools import (
            sentry_get_issue_details,
            sentry_get_project_stats,
            sentry_list_issues,
            sentry_list_projects,
            sentry_list_releases,
            sentry_update_issue_status,
        )

        tools.extend(
            [
                sentry_list_issues,
                sentry_get_issue_details,
                sentry_update_issue_status,
                sentry_list_projects,
                sentry_get_project_stats,
                sentry_list_releases,
            ]
        )
        logger.debug("sentry_tools_loaded", count=6)
    except Exception as e:
        logger.warning("sentry_tools_load_failed", error=str(e))

    # Splunk tools (if splunk-sdk available)
    if is_integration_available("splunklib"):
        try:
            from .splunk_tools import (
                splunk_get_alerts,
                splunk_get_saved_searches,
                splunk_list_indexes,
                splunk_search,
            )

            tools.extend(
                [
                    splunk_search,
                    splunk_list_indexes,
                    splunk_get_saved_searches,
                    splunk_get_alerts,
                ]
            )
            logger.debug("splunk_tools_loaded", count=4)
        except Exception as e:
            logger.warning("splunk_tools_load_failed", error=str(e))

    # Jira tools (if jira package available)
    if is_integration_available("jira"):
        try:
            from .jira_tools import (
                jira_add_comment,
                jira_create_epic,
                jira_create_issue,
                jira_get_issue,
                jira_list_issues,
                jira_update_issue,
            )

            tools.extend(
                [
                    jira_create_issue,
                    jira_create_epic,
                    jira_get_issue,
                    jira_add_comment,
                    jira_update_issue,
                    jira_list_issues,
                ]
            )
            logger.debug("jira_tools_loaded", count=6)
        except Exception as e:
            logger.warning("jira_tools_load_failed", error=str(e))

    # GitLab tools (if python-gitlab available)
    if is_integration_available("gitlab"):
        try:
            from .gitlab_tools import (
                gitlab_add_mr_comment,
                gitlab_get_merge_requests,
                gitlab_get_pipeline_jobs,
                gitlab_get_pipelines,
                gitlab_list_projects,
            )

            tools.extend(
                [
                    gitlab_list_projects,
                    gitlab_get_pipelines,
                    gitlab_get_merge_requests,
                    gitlab_add_mr_comment,
                    gitlab_get_pipeline_jobs,
                ]
            )
            logger.debug("gitlab_tools_loaded", count=5)
        except Exception as e:
            logger.warning("gitlab_tools_load_failed", error=str(e))

    # Linear tools (uses requests - core dependency)
    try:
        from .linear_tools import (
            linear_create_issue,
            linear_create_project,
            linear_get_issue,
            linear_list_issues,
        )

        tools.extend(
            [
                linear_create_issue,
                linear_create_project,
                linear_get_issue,
                linear_list_issues,
            ]
        )
        logger.debug("linear_tools_loaded", count=4)
    except Exception as e:
        logger.warning("linear_tools_load_failed", error=str(e))

    # Notion tools (if notion-client available)
    if is_integration_available("notion_client"):
        try:
            from .notion_tools import (
                notion_create_page,
                notion_search,
                notion_write_content,
            )

            tools.extend(
                [
                    notion_create_page,
                    notion_write_content,
                    notion_search,
                ]
            )
            logger.debug("notion_tools_loaded", count=3)
        except Exception as e:
            logger.warning("notion_tools_load_failed", error=str(e))

    # Microsoft Teams tools (uses requests - core dependency)
    try:
        from .msteams_tools import (
            send_teams_adaptive_card,
            send_teams_alert,
            send_teams_message,
        )

        tools.extend(
            [
                send_teams_message,
                send_teams_adaptive_card,
                send_teams_alert,
            ]
        )
        logger.debug("msteams_tools_loaded", count=3)
    except Exception as e:
        logger.warning("msteams_tools_load_failed", error=str(e))

    # Load MCP tools (dynamically discovered from configured MCP servers)
    try:
        from ..core.mcp_client import get_mcp_tools_for_agent

        team_config = config.team_config
        if team_config and hasattr(team_config, "team_id"):
            team_id = team_config.team_id
            mcp_tools = get_mcp_tools_for_agent(team_id, agent_name)
            tools.extend(mcp_tools)
            logger.debug("mcp_tools_loaded", count=len(mcp_tools))
    except Exception as e:
        logger.warning("mcp_tools_load_failed", error=str(e))

    logger.info("tools_loaded_for_agent", agent=agent_name, total_tools=len(tools))
    # The OpenAI Agents SDK expects Tool objects (with `.name`), not raw callables.
    # Wrap functions into FunctionTool for compatibility and better tracing.
    try:
        from agents import Tool, function_tool  # type: ignore
    except Exception:
        return tools

    wrapped: list[Any] = []
    for t in tools:
        try:
            if isinstance(t, Tool):
                wrapped.append(t)
            elif hasattr(t, "name"):
                # Already a FunctionTool or similar
                wrapped.append(t)
            else:
                # Try to wrap, but skip on schema errors
                try:
                    wrapped.append(function_tool(t, strict_mode=False))
                except TypeError:
                    # Older SDK version without strict_mode
                    wrapped.append(function_tool(t))
        except Exception as e:
            # If wrapping fails, skip this tool rather than crash
            logger.warning(
                "tool_wrap_failed", tool=str(getattr(t, "__name__", t)), error=str(e)
            )
            # Still include the raw function - some SDK versions accept it
            wrapped.append(t)
    return wrapped
