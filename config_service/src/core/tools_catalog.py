"""
Built-in tools catalog metadata.

This module contains static metadata for all built-in tools available in the agent service.
This allows the Config Service to return tool catalog without needing to connect to MCP servers.

Each tool includes:
- id: Unique tool identifier
- name: Human-readable tool name
- description: What the tool does
- category: Tool category for organization
- required_integrations: List of integration IDs this tool requires to function
"""

from typing import Any, Dict, List


def _infer_tool_category(tool_name: str) -> str:
    """Infer tool category from tool name."""
    name_lower = tool_name.lower()

    if any(k in name_lower for k in ["k8s", "pod", "deployment", "kubernetes", "eks"]):
        return "kubernetes"
    elif any(
        k in name_lower
        for k in ["aws", "ec2", "s3", "lambda", "cloudwatch", "rds", "ecs"]
    ):
        return "aws"
    elif any(
        k in name_lower
        for k in ["github", "git", "pr", "pull_request", "commit", "branch", "issue"]
    ):
        return "github"
    elif any(k in name_lower for k in ["slack"]):
        return "communication"
    elif any(
        k in name_lower
        for k in [
            "grafana",
            "prometheus",
            "coralogix",
            "metrics",
            "alert",
            "logs",
            "trace",
        ]
    ):
        return "observability"
    elif any(
        k in name_lower
        for k in ["snowflake", "bigquery", "postgres", "sql", "query", "database"]
    ):
        return "data"
    elif any(k in name_lower for k in ["anomal", "correlate", "detect", "forecast"]):
        return "analytics"
    elif any(k in name_lower for k in ["docker", "container"]):
        return "docker"
    elif any(
        k in name_lower
        for k in ["pipeline", "workflow", "codepipeline", "cicd", "ci", "cd"]
    ):
        return "cicd"
    elif any(
        k in name_lower
        for k in [
            "file",
            "read",
            "write",
            "filesystem",
            "directory",
            "path",
            "repo_search",
        ]
    ):
        return "filesystem"
    elif any(k in name_lower for k in ["incident", "pagerduty"]):
        return "incident"
    elif any(k in name_lower for k in ["think", "llm", "agent"]):
        return "agent"
    else:
        return "other"


# Static list of all built-in tools with integration dependencies
# This mirrors the tools loaded in agent/src/ai_agent/tools/tool_loader.py
BUILT_IN_TOOLS_METADATA = [
    # Core agent tool (no integration required)
    {
        "id": "think",
        "name": "Think",
        "description": "Internal reasoning and planning tool",
        "category": "agent",
        "required_integrations": [],
    },
    # Kubernetes tools
    {
        "id": "get_pod_logs",
        "name": "Get Pod Logs",
        "description": "Fetch logs from a Kubernetes pod",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "describe_pod",
        "name": "Describe Pod",
        "description": "Get detailed information about a Kubernetes pod",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "list_pods",
        "name": "List Pods",
        "description": "List all pods in a namespace",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "get_pod_events",
        "name": "Get Pod Events",
        "description": "Get events related to a pod",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "describe_deployment",
        "name": "Describe Deployment",
        "description": "Get detailed information about a deployment",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "get_deployment_history",
        "name": "Get Deployment History",
        "description": "Get rollout history of a deployment",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "describe_service",
        "name": "Describe Service",
        "description": "Get information about a Kubernetes service",
        "category": "other",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "get_pod_resource_usage",
        "name": "Get Pod Resource Usage",
        "description": "Get CPU and memory usage of pods",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    # AWS tools
    {
        "id": "describe_ec2_instance",
        "name": "Describe EC2 Instance",
        "description": "Get information about an EC2 instance",
        "category": "aws",
        "required_integrations": ["aws"],
    },
    {
        "id": "get_cloudwatch_logs",
        "name": "Get CloudWatch Logs",
        "description": "Query CloudWatch logs",
        "category": "aws",
        "required_integrations": ["aws"],
    },
    {
        "id": "describe_lambda_function",
        "name": "Describe Lambda Function",
        "description": "Get information about a Lambda function",
        "category": "aws",
        "required_integrations": ["aws"],
    },
    {
        "id": "get_rds_instance_status",
        "name": "Get RDS Instance Status",
        "description": "Get status of an RDS database instance",
        "category": "other",
        "required_integrations": ["aws"],
    },
    {
        "id": "query_cloudwatch_insights",
        "name": "Query CloudWatch Insights",
        "description": "Run CloudWatch Insights queries",
        "category": "aws",
        "required_integrations": ["aws"],
    },
    {
        "id": "get_cloudwatch_metrics",
        "name": "Get CloudWatch Metrics",
        "description": "Get CloudWatch metrics data",
        "category": "aws",
        "required_integrations": ["aws"],
    },
    {
        "id": "list_ecs_tasks",
        "name": "List ECS Tasks",
        "description": "List ECS tasks in a cluster",
        "category": "other",
        "required_integrations": ["aws"],
    },
    # Slack tools
    {
        "id": "search_slack_messages",
        "name": "Search Slack Messages",
        "description": "Search for messages in Slack",
        "category": "communication",
        "required_integrations": ["slack"],
    },
    {
        "id": "get_channel_history",
        "name": "Get Channel History",
        "description": "Get message history from a Slack channel",
        "category": "communication",
        "required_integrations": ["slack"],
    },
    {
        "id": "get_thread_replies",
        "name": "Get Thread Replies",
        "description": "Get replies in a Slack thread",
        "category": "communication",
        "required_integrations": ["slack"],
    },
    {
        "id": "post_slack_message",
        "name": "Post Slack Message",
        "description": "Post a message to Slack",
        "category": "communication",
        "required_integrations": ["slack"],
    },
    # GitHub tools
    {
        "id": "search_github_code",
        "name": "Search GitHub Code",
        "description": "Search code in GitHub repositories",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "read_github_file",
        "name": "Read GitHub File",
        "description": "Read a file from a GitHub repository",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "create_pull_request",
        "name": "Create Pull Request",
        "description": "Create a pull request on GitHub",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "list_pull_requests",
        "name": "List Pull Requests",
        "description": "List pull requests in a repository",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "merge_pull_request",
        "name": "Merge Pull Request",
        "description": "Merge a pull request",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "create_issue",
        "name": "Create Issue",
        "description": "Create an issue on GitHub",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "list_issues",
        "name": "List Issues",
        "description": "List issues in a repository",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "close_issue",
        "name": "Close Issue",
        "description": "Close a GitHub issue",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "create_branch",
        "name": "Create Branch",
        "description": "Create a new branch in a repository",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "list_branches",
        "name": "List Branches",
        "description": "List branches in a repository",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "list_files",
        "name": "List Files",
        "description": "List files in a GitHub repository",
        "category": "filesystem",
        "required_integrations": ["github"],
    },
    {
        "id": "get_repo_info",
        "name": "Get Repo Info",
        "description": "Get information about a GitHub repository",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "trigger_workflow",
        "name": "Trigger Workflow",
        "description": "Trigger a GitHub Actions workflow",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "list_workflow_runs",
        "name": "List Workflow Runs",
        "description": "List GitHub Actions workflow runs",
        "category": "github",
        "required_integrations": ["github"],
    },
    # Elasticsearch tools
    {
        "id": "search_logs",
        "name": "Search Logs",
        "description": "Search logs in Elasticsearch",
        "category": "observability",
        "required_integrations": ["elasticsearch"],
    },
    {
        "id": "aggregate_errors_by_field",
        "name": "Aggregate Errors By Field",
        "description": "Aggregate errors by field in Elasticsearch",
        "category": "observability",
        "required_integrations": ["elasticsearch"],
    },
    # Confluence tools
    {
        "id": "search_confluence",
        "name": "Search Confluence",
        "description": "Search Confluence pages",
        "category": "other",
        "required_integrations": ["confluence"],
    },
    {
        "id": "get_confluence_page",
        "name": "Get Confluence Page",
        "description": "Get a Confluence page by ID",
        "category": "other",
        "required_integrations": ["confluence"],
    },
    {
        "id": "list_space_pages",
        "name": "List Space Pages",
        "description": "List pages in a Confluence space",
        "category": "other",
        "required_integrations": ["confluence"],
    },
    # Sourcegraph tools
    {
        "id": "search_sourcegraph",
        "name": "Search Sourcegraph",
        "description": "Search code using Sourcegraph",
        "category": "other",
        "required_integrations": ["sourcegraph"],
    },
    # Datadog tools
    {
        "id": "query_datadog_metrics",
        "name": "Query Datadog Metrics",
        "description": "Query metrics from Datadog",
        "category": "observability",
        "required_integrations": ["datadog"],
    },
    {
        "id": "search_datadog_logs",
        "name": "Search Datadog Logs",
        "description": "Search logs in Datadog",
        "category": "observability",
        "required_integrations": ["datadog"],
    },
    {
        "id": "get_service_apm_metrics",
        "name": "Get Service APM Metrics",
        "description": "Get APM metrics for a service from Datadog",
        "category": "observability",
        "required_integrations": ["datadog"],
    },
    # New Relic tools
    {
        "id": "query_newrelic_nrql",
        "name": "Query NewRelic NRQL",
        "description": "Run NRQL queries in New Relic",
        "category": "observability",
        "required_integrations": ["newrelic"],
    },
    {
        "id": "get_apm_summary",
        "name": "Get APM Summary",
        "description": "Get APM summary from New Relic",
        "category": "observability",
        "required_integrations": ["newrelic"],
    },
    # Google Docs tools
    {
        "id": "read_google_doc",
        "name": "Read Google Doc",
        "description": "Read a Google Doc",
        "category": "other",
        "required_integrations": ["google_docs"],
    },
    {
        "id": "search_google_drive",
        "name": "Search Google Drive",
        "description": "Search for files in Google Drive",
        "category": "other",
        "required_integrations": ["google_docs"],
    },
    {
        "id": "list_folder_contents",
        "name": "List Folder Contents",
        "description": "List contents of a Google Drive folder",
        "category": "other",
        "required_integrations": ["google_docs"],
    },
    # Git tools (local, no integration required)
    {
        "id": "git_status",
        "name": "Git Status",
        "description": "Get git status",
        "category": "github",
        "required_integrations": [],
    },
    {
        "id": "git_diff",
        "name": "Git Diff",
        "description": "Get git diff",
        "category": "github",
        "required_integrations": [],
    },
    {
        "id": "git_log",
        "name": "Git Log",
        "description": "Get git log",
        "category": "github",
        "required_integrations": [],
    },
    {
        "id": "git_blame",
        "name": "Git Blame",
        "description": "Get git blame",
        "category": "github",
        "required_integrations": [],
    },
    {
        "id": "git_show",
        "name": "Git Show",
        "description": "Show git commit details",
        "category": "github",
        "required_integrations": [],
    },
    {
        "id": "git_branch_list",
        "name": "Git Branch List",
        "description": "List git branches",
        "category": "github",
        "required_integrations": [],
    },
    # Docker tools (local, no integration required)
    {
        "id": "docker_ps",
        "name": "Docker PS",
        "description": "List Docker containers",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_logs",
        "name": "Docker Logs",
        "description": "Get Docker container logs",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_inspect",
        "name": "Docker Inspect",
        "description": "Inspect Docker container",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_exec",
        "name": "Docker Exec",
        "description": "Execute command in Docker container",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_images",
        "name": "Docker Images",
        "description": "List Docker images",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_stats",
        "name": "Docker Stats",
        "description": "Get Docker container stats",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_compose_ps",
        "name": "Docker Compose PS",
        "description": "List Docker Compose services",
        "category": "docker",
        "required_integrations": [],
    },
    {
        "id": "docker_compose_logs",
        "name": "Docker Compose Logs",
        "description": "Get Docker Compose service logs",
        "category": "docker",
        "required_integrations": [],
    },
    # Coding tools (local filesystem, no integration required)
    {
        "id": "repo_search_text",
        "name": "Repo Search Text",
        "description": "Search text in repository",
        "category": "filesystem",
        "required_integrations": [],
    },
    {
        "id": "python_run_tests",
        "name": "Python Run Tests",
        "description": "Run Python tests",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "pytest_run",
        "name": "Pytest Run",
        "description": "Run pytest",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "read_file",
        "name": "Read File",
        "description": "Read a file from filesystem",
        "category": "filesystem",
        "required_integrations": [],
    },
    {
        "id": "write_file",
        "name": "Write File",
        "description": "Write content to a file",
        "category": "filesystem",
        "required_integrations": [],
    },
    {
        "id": "list_directory",
        "name": "List Directory",
        "description": "List contents of a directory",
        "category": "filesystem",
        "required_integrations": [],
    },
    {
        "id": "run_linter",
        "name": "Run Linter",
        "description": "Run code linter",
        "category": "other",
        "required_integrations": [],
    },
    # Browser tools (no integration required)
    {
        "id": "browser_screenshot",
        "name": "Browser Screenshot",
        "description": "Take screenshot of webpage",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "browser_scrape",
        "name": "Browser Scrape",
        "description": "Scrape webpage content",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "browser_fetch_html",
        "name": "Browser Fetch HTML",
        "description": "Fetch HTML from webpage",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "browser_pdf",
        "name": "Browser PDF",
        "description": "Generate PDF from webpage",
        "category": "other",
        "required_integrations": [],
    },
    # Package tools (no integration required)
    {
        "id": "pip_install",
        "name": "Pip Install",
        "description": "Install Python packages with pip",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "pip_list",
        "name": "Pip List",
        "description": "List installed Python packages",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "pip_freeze",
        "name": "Pip Freeze",
        "description": "Freeze Python package requirements",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "npm_install",
        "name": "NPM Install",
        "description": "Install Node.js packages with npm",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "npm_run",
        "name": "NPM Run",
        "description": "Run npm scripts",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "yarn_install",
        "name": "Yarn Install",
        "description": "Install Node.js packages with yarn",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "poetry_install",
        "name": "Poetry Install",
        "description": "Install Python packages with Poetry",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "venv_create",
        "name": "Venv Create",
        "description": "Create Python virtual environment",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "check_tool_available",
        "name": "Check Tool Available",
        "description": "Check if a command-line tool is available",
        "category": "other",
        "required_integrations": [],
    },
    # Anomaly detection tools (no integration required - statistical analysis)
    {
        "id": "detect_anomalies",
        "name": "Detect Anomalies",
        "description": "Detect anomalies in time series data",
        "category": "analytics",
        "required_integrations": [],
    },
    {
        "id": "correlate_metrics",
        "name": "Correlate Metrics",
        "description": "Correlate multiple metrics",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "find_change_point",
        "name": "Find Change Point",
        "description": "Find change points in time series",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "forecast_metric",
        "name": "Forecast Metric",
        "description": "Forecast metric values",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "analyze_metric_distribution",
        "name": "Analyze Metric Distribution",
        "description": "Analyze metric distribution",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "prophet_detect_anomalies",
        "name": "Prophet Detect Anomalies",
        "description": "Detect anomalies using Prophet",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "prophet_forecast",
        "name": "Prophet Forecast",
        "description": "Forecast using Prophet",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "prophet_decompose",
        "name": "Prophet Decompose",
        "description": "Decompose time series using Prophet",
        "category": "other",
        "required_integrations": [],
    },
    # Grafana tools
    {
        "id": "grafana_list_dashboards",
        "name": "Grafana List Dashboards",
        "description": "List Grafana dashboards",
        "category": "observability",
        "required_integrations": ["grafana"],
    },
    {
        "id": "grafana_get_dashboard",
        "name": "Grafana Get Dashboard",
        "description": "Get Grafana dashboard",
        "category": "observability",
        "required_integrations": ["grafana"],
    },
    {
        "id": "grafana_query_prometheus",
        "name": "Grafana Query Prometheus",
        "description": "Query Prometheus via Grafana",
        "category": "observability",
        "required_integrations": ["grafana"],
    },
    {
        "id": "grafana_list_datasources",
        "name": "Grafana List Datasources",
        "description": "List Grafana datasources",
        "category": "observability",
        "required_integrations": ["grafana"],
    },
    {
        "id": "grafana_get_annotations",
        "name": "Grafana Get Annotations",
        "description": "Get Grafana annotations",
        "category": "observability",
        "required_integrations": ["grafana"],
    },
    {
        "id": "grafana_get_alerts",
        "name": "Grafana Get Alerts",
        "description": "Get Grafana alerts",
        "category": "observability",
        "required_integrations": ["grafana"],
    },
    # Knowledge Base tools (internal, no integration required)
    {
        "id": "search_knowledge_base",
        "name": "Search Knowledge Base",
        "description": "Search the knowledge base",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "ask_knowledge_base",
        "name": "Ask Knowledge Base",
        "description": "Ask a question to the knowledge base",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "get_knowledge_context",
        "name": "Get Knowledge Context",
        "description": "Get context from knowledge base",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "list_knowledge_trees",
        "name": "List Knowledge Trees",
        "description": "List knowledge base trees",
        "category": "other",
        "required_integrations": [],
    },
    # Remediation tools (internal, no integration required)
    {
        "id": "propose_remediation",
        "name": "Propose Remediation",
        "description": "Propose a remediation action",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "propose_pod_restart",
        "name": "Propose Pod Restart",
        "description": "Propose restarting a pod",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "propose_deployment_restart",
        "name": "Propose Deployment Restart",
        "description": "Propose restarting a deployment",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "propose_scale_deployment",
        "name": "Propose Scale Deployment",
        "description": "Propose scaling a deployment",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "propose_deployment_rollback",
        "name": "Propose Deployment Rollback",
        "description": "Propose rolling back a deployment",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "propose_emergency_action",
        "name": "Propose Emergency Action",
        "description": "Propose an emergency action",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "get_current_replicas",
        "name": "Get Current Replicas",
        "description": "Get current replica count",
        "category": "kubernetes",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "list_pending_remediations",
        "name": "List Pending Remediations",
        "description": "List pending remediation actions",
        "category": "other",
        "required_integrations": [],
    },
    {
        "id": "get_remediation_status",
        "name": "Get Remediation Status",
        "description": "Get status of a remediation action",
        "category": "other",
        "required_integrations": [],
    },
    # Snowflake tools
    {
        "id": "get_snowflake_schema",
        "name": "Get Snowflake Schema",
        "description": "Get Snowflake database schema",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "run_snowflake_query",
        "name": "Run Snowflake Query",
        "description": "Run a query in Snowflake",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "get_recent_incidents",
        "name": "Get Recent Incidents",
        "description": "Get recent incidents from Snowflake",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "get_incident_customer_impact",
        "name": "Get Incident Customer Impact",
        "description": "Get customer impact of incidents",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "get_deployment_incidents",
        "name": "Get Deployment Incidents",
        "description": "Get incidents related to deployments",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "get_customer_info",
        "name": "Get Customer Info",
        "description": "Get customer information from Snowflake",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "get_incident_timeline",
        "name": "Get Incident Timeline",
        "description": "Get incident timeline from Snowflake",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "search_incidents_by_service",
        "name": "Search Incidents By Service",
        "description": "Search incidents by service name in Snowflake",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "snowflake_list_tables",
        "name": "Snowflake List Tables",
        "description": "List all tables in a Snowflake database/schema",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "snowflake_describe_table",
        "name": "Snowflake Describe Table",
        "description": "Get column details for a Snowflake table",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    {
        "id": "snowflake_bulk_export",
        "name": "Snowflake Bulk Export",
        "description": "Export query results to Snowflake stage for bulk data transfer",
        "category": "data",
        "required_integrations": ["snowflake"],
    },
    # Coralogix tools
    {
        "id": "search_coralogix_logs",
        "name": "Search Coralogix Logs",
        "description": "Search logs in Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "get_coralogix_error_logs",
        "name": "Get Coralogix Error Logs",
        "description": "Get error logs from Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "get_coralogix_alerts",
        "name": "Get Coralogix Alerts",
        "description": "Get alerts from Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "query_coralogix_metrics",
        "name": "Query Coralogix Metrics",
        "description": "Query metrics in Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "search_coralogix_traces",
        "name": "Search Coralogix Traces",
        "description": "Search traces in Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "get_coralogix_service_health",
        "name": "Get Coralogix Service Health",
        "description": "Get service health from Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "list_coralogix_services",
        "name": "List Coralogix Services",
        "description": "List services in Coralogix",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    # PagerDuty tools
    {
        "id": "pagerduty_get_incident",
        "name": "PagerDuty Get Incident",
        "description": "Get details of a PagerDuty incident",
        "category": "incident",
        "required_integrations": ["pagerduty"],
    },
    {
        "id": "pagerduty_get_incident_log_entries",
        "name": "PagerDuty Get Incident Log",
        "description": "Get log entries for a PagerDuty incident",
        "category": "incident",
        "required_integrations": ["pagerduty"],
    },
    {
        "id": "pagerduty_list_incidents",
        "name": "PagerDuty List Incidents",
        "description": "List PagerDuty incidents",
        "category": "incident",
        "required_integrations": ["pagerduty"],
    },
    {
        "id": "pagerduty_get_escalation_policy",
        "name": "PagerDuty Get Escalation Policy",
        "description": "Get PagerDuty escalation policy",
        "category": "incident",
        "required_integrations": ["pagerduty"],
    },
    {
        "id": "pagerduty_calculate_mttr",
        "name": "PagerDuty Calculate MTTR",
        "description": "Calculate mean time to resolution",
        "category": "analytics",
        "required_integrations": ["pagerduty"],
    },
    # BigQuery tools
    {
        "id": "bigquery_query",
        "name": "BigQuery Query",
        "description": "Execute SQL query on BigQuery",
        "category": "data",
        "required_integrations": ["bigquery"],
    },
    {
        "id": "bigquery_list_datasets",
        "name": "BigQuery List Datasets",
        "description": "List all BigQuery datasets",
        "category": "data",
        "required_integrations": ["bigquery"],
    },
    {
        "id": "bigquery_list_tables",
        "name": "BigQuery List Tables",
        "description": "List tables in a BigQuery dataset",
        "category": "data",
        "required_integrations": ["bigquery"],
    },
    {
        "id": "bigquery_get_table_schema",
        "name": "BigQuery Get Table Schema",
        "description": "Get schema of a BigQuery table",
        "category": "data",
        "required_integrations": ["bigquery"],
    },
    # PostgreSQL tools (works with RDS, Aurora, standard PostgreSQL)
    {
        "id": "postgres_list_tables",
        "name": "PostgreSQL List Tables",
        "description": "List all tables in a PostgreSQL database schema",
        "category": "data",
        "required_integrations": ["postgresql"],
    },
    {
        "id": "postgres_describe_table",
        "name": "PostgreSQL Describe Table",
        "description": "Get column details, primary keys, and foreign keys for a PostgreSQL table",
        "category": "data",
        "required_integrations": ["postgresql"],
    },
    {
        "id": "postgres_execute_query",
        "name": "PostgreSQL Execute Query",
        "description": "Execute SQL query against PostgreSQL and return results",
        "category": "data",
        "required_integrations": ["postgresql"],
    },
    # Splunk tools
    {
        "id": "splunk_search",
        "name": "Splunk Search",
        "description": "Execute SPL search query in Splunk",
        "category": "observability",
        "required_integrations": ["splunk"],
    },
    {
        "id": "splunk_list_indexes",
        "name": "Splunk List Indexes",
        "description": "List all Splunk indexes",
        "category": "observability",
        "required_integrations": ["splunk"],
    },
    {
        "id": "splunk_get_saved_searches",
        "name": "Splunk Get Saved Searches",
        "description": "Get Splunk saved searches and alerts",
        "category": "observability",
        "required_integrations": ["splunk"],
    },
    {
        "id": "splunk_get_alerts",
        "name": "Splunk Get Alerts",
        "description": "Get triggered Splunk alerts",
        "category": "observability",
        "required_integrations": ["splunk"],
    },
    # Microsoft Teams tools
    {
        "id": "send_teams_message",
        "name": "Send Teams Message",
        "description": "Send message to Microsoft Teams",
        "category": "communication",
        "required_integrations": ["msteams"],
    },
    {
        "id": "send_teams_adaptive_card",
        "name": "Send Teams Adaptive Card",
        "description": "Send adaptive card to Microsoft Teams",
        "category": "communication",
        "required_integrations": ["msteams"],
    },
    {
        "id": "send_teams_alert",
        "name": "Send Teams Alert",
        "description": "Send formatted alert to Microsoft Teams",
        "category": "communication",
        "required_integrations": ["msteams"],
    },
    # GitHub App tools
    {
        "id": "github_app_create_check_run",
        "name": "GitHub App Create Check Run",
        "description": "Create check run on GitHub commit",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "github_app_add_pr_comment",
        "name": "GitHub App Add PR Comment",
        "description": "Add comment to GitHub pull request",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "github_app_update_pr_status",
        "name": "GitHub App Update PR Status",
        "description": "Update GitHub commit status",
        "category": "github",
        "required_integrations": ["github"],
    },
    {
        "id": "github_app_list_installations",
        "name": "GitHub App List Installations",
        "description": "List GitHub App installations",
        "category": "github",
        "required_integrations": ["github"],
    },
    # GitLab tools
    {
        "id": "gitlab_list_projects",
        "name": "GitLab List Projects",
        "description": "List GitLab projects",
        "category": "github",
        "required_integrations": ["gitlab"],
    },
    {
        "id": "gitlab_get_pipelines",
        "name": "GitLab Get Pipelines",
        "description": "Get GitLab CI/CD pipelines",
        "category": "cicd",
        "required_integrations": ["gitlab"],
    },
    {
        "id": "gitlab_get_merge_requests",
        "name": "GitLab Get Merge Requests",
        "description": "List GitLab merge requests",
        "category": "github",
        "required_integrations": ["gitlab"],
    },
    {
        "id": "gitlab_add_mr_comment",
        "name": "GitLab Add MR Comment",
        "description": "Add comment to GitLab merge request",
        "category": "github",
        "required_integrations": ["gitlab"],
    },
    {
        "id": "gitlab_get_pipeline_jobs",
        "name": "GitLab Get Pipeline Jobs",
        "description": "Get jobs for GitLab pipeline",
        "category": "cicd",
        "required_integrations": ["gitlab"],
    },
    # AWS CodePipeline tools
    {
        "id": "codepipeline_list_pipelines",
        "name": "CodePipeline List Pipelines",
        "description": "List AWS CodePipeline pipelines",
        "category": "cicd",
        "required_integrations": ["aws"],
    },
    {
        "id": "codepipeline_get_pipeline_state",
        "name": "CodePipeline Get Pipeline State",
        "description": "Get AWS CodePipeline state",
        "category": "cicd",
        "required_integrations": ["aws"],
    },
    {
        "id": "codepipeline_get_execution_history",
        "name": "CodePipeline Get Execution History",
        "description": "Get CodePipeline execution history",
        "category": "cicd",
        "required_integrations": ["aws"],
    },
    {
        "id": "codepipeline_start_execution",
        "name": "CodePipeline Start Execution",
        "description": "Trigger AWS CodePipeline execution",
        "category": "cicd",
        "required_integrations": ["aws"],
    },
    {
        "id": "codepipeline_get_failed_actions",
        "name": "CodePipeline Get Failed Actions",
        "description": "Get failed CodePipeline actions",
        "category": "cicd",
        "required_integrations": ["aws"],
    },
    # GCP tools
    {
        "id": "gcp_list_compute_instances",
        "name": "GCP List Compute Instances",
        "description": "List GCP Compute Engine instances",
        "category": "cloud",
        "required_integrations": ["gcp"],
    },
    {
        "id": "gcp_list_gke_clusters",
        "name": "GCP List GKE Clusters",
        "description": "List Google Kubernetes Engine clusters",
        "category": "kubernetes",
        "required_integrations": ["gcp"],
    },
    {
        "id": "gcp_list_cloud_functions",
        "name": "GCP List Cloud Functions",
        "description": "List GCP Cloud Functions",
        "category": "cloud",
        "required_integrations": ["gcp"],
    },
    {
        "id": "gcp_list_cloud_sql_instances",
        "name": "GCP List Cloud SQL Instances",
        "description": "List GCP Cloud SQL instances",
        "category": "data",
        "required_integrations": ["gcp"],
    },
    {
        "id": "gcp_get_project_metadata",
        "name": "GCP Get Project Metadata",
        "description": "Get GCP project metadata",
        "category": "cloud",
        "required_integrations": ["gcp"],
    },
    # Sentry tools
    {
        "id": "sentry_list_issues",
        "name": "Sentry List Issues",
        "description": "List Sentry error issues",
        "category": "observability",
        "required_integrations": ["sentry"],
    },
    {
        "id": "sentry_get_issue_details",
        "name": "Sentry Get Issue Details",
        "description": "Get details of a Sentry issue",
        "category": "observability",
        "required_integrations": ["sentry"],
    },
    {
        "id": "sentry_update_issue_status",
        "name": "Sentry Update Issue Status",
        "description": "Update Sentry issue status",
        "category": "observability",
        "required_integrations": ["sentry"],
    },
    {
        "id": "sentry_list_projects",
        "name": "Sentry List Projects",
        "description": "List Sentry projects",
        "category": "observability",
        "required_integrations": ["sentry"],
    },
    {
        "id": "sentry_get_project_stats",
        "name": "Sentry Get Project Stats",
        "description": "Get Sentry project statistics",
        "category": "analytics",
        "required_integrations": ["sentry"],
    },
    {
        "id": "sentry_list_releases",
        "name": "Sentry List Releases",
        "description": "List Sentry releases",
        "category": "observability",
        "required_integrations": ["sentry"],
    },
    # Jira tools
    {
        "id": "jira_create_issue",
        "name": "Jira Create Issue",
        "description": "Create a Jira issue",
        "category": "other",
        "required_integrations": ["jira"],
    },
    {
        "id": "jira_create_epic",
        "name": "Jira Create Epic",
        "description": "Create a Jira epic",
        "category": "other",
        "required_integrations": ["jira"],
    },
    {
        "id": "jira_get_issue",
        "name": "Jira Get Issue",
        "description": "Get details of a Jira issue",
        "category": "other",
        "required_integrations": ["jira"],
    },
    {
        "id": "jira_add_comment",
        "name": "Jira Add Comment",
        "description": "Add comment to Jira issue",
        "category": "other",
        "required_integrations": ["jira"],
    },
    {
        "id": "jira_update_issue",
        "name": "Jira Update Issue",
        "description": "Update a Jira issue",
        "category": "other",
        "required_integrations": ["jira"],
    },
    {
        "id": "jira_list_issues",
        "name": "Jira List Issues",
        "description": "List Jira issues in a project",
        "category": "other",
        "required_integrations": ["jira"],
    },
    # Linear tools
    {
        "id": "linear_create_issue",
        "name": "Linear Create Issue",
        "description": "Create a Linear issue",
        "category": "other",
        "required_integrations": ["linear"],
    },
    {
        "id": "linear_create_project",
        "name": "Linear Create Project",
        "description": "Create a Linear project",
        "category": "other",
        "required_integrations": ["linear"],
    },
    {
        "id": "linear_get_issue",
        "name": "Linear Get Issue",
        "description": "Get details of a Linear issue",
        "category": "other",
        "required_integrations": ["linear"],
    },
    {
        "id": "linear_list_issues",
        "name": "Linear List Issues",
        "description": "List Linear issues",
        "category": "other",
        "required_integrations": ["linear"],
    },
    # Notion tools
    {
        "id": "notion_create_page",
        "name": "Notion Create Page",
        "description": "Create a Notion page",
        "category": "other",
        "required_integrations": ["notion"],
    },
    {
        "id": "notion_write_content",
        "name": "Notion Write Content",
        "description": "Write content to a Notion page",
        "category": "other",
        "required_integrations": ["notion"],
    },
    {
        "id": "notion_search",
        "name": "Notion Search",
        "description": "Search Notion pages",
        "category": "other",
        "required_integrations": ["notion"],
    },
]


def get_built_in_tools() -> List[Dict[str, Any]]:
    """
    Get list of all built-in tools with integration dependencies.

    Returns:
        List of tool metadata dicts with id, name, description, category, source, required_integrations
    """
    return [
        {
            **tool,
            "source": "built-in",
        }
        for tool in BUILT_IN_TOOLS_METADATA
    ]


def get_tools_by_integration(integration_id: str) -> List[Dict[str, Any]]:
    """
    Get all tools that require a specific integration.

    This is useful for showing users "what they get" when they configure an integration.

    Args:
        integration_id: The integration ID (e.g., "grafana", "kubernetes", "github")

    Returns:
        List of tool metadata dicts that require this integration
    """
    return [
        {**tool, "source": "built-in"}
        for tool in BUILT_IN_TOOLS_METADATA
        if integration_id in tool.get("required_integrations", [])
    ]


def get_mcp_tools_metadata(
    team_mcps_config: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Get tool metadata for MCP servers from team configuration.

    This returns metadata WITHOUT connecting to actual MCP servers.
    We extract tool information from MCP configuration where available,
    or return placeholder metadata.

    Args:
        team_mcps_config: List of MCP server configurations from team config

    Returns:
        List of tool metadata dicts
    """
    mcp_tools = []

    for mcp_config in team_mcps_config:
        if not mcp_config.get("enabled", True):
            continue

        mcp_id = mcp_config.get("id", "")
        mcp_name = mcp_config.get("name", mcp_id)

        # If MCP config has tools list, use it
        # Otherwise, generate placeholder based on MCP type
        if "tools" in mcp_config:
            for tool in mcp_config["tools"]:
                mcp_tools.append(
                    {
                        "id": tool.get("name", ""),
                        "name": tool.get("display_name", tool.get("name", "")),
                        "description": tool.get("description", f"Tool from {mcp_name}"),
                        "category": _infer_tool_category(tool.get("name", "")),
                        "source": "mcp",
                        "mcp_server": mcp_id,
                        "required_integrations": [],  # MCP tools handled by MCP server itself
                    }
                )
        else:
            # Placeholder - indicate MCP server is configured but tools unknown
            # In production, you might want to maintain a registry of known MCP server types
            mcp_tools.append(
                {
                    "id": f"{mcp_id}_tools",
                    "name": f"{mcp_name} Tools",
                    "description": f"Tools provided by {mcp_name} MCP server",
                    "category": "other",
                    "source": "mcp",
                    "mcp_server": mcp_id,
                    "required_integrations": [],
                }
            )

    return mcp_tools


def get_tools_catalog(team_mcps_config: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get complete tools catalog for a team.

    Args:
        team_mcps_config: Optional list of MCP configurations for the team

    Returns:
        Dict with 'tools' list and 'count'
    """
    built_in = get_built_in_tools()
    mcp_tools = get_mcp_tools_metadata(team_mcps_config or [])

    all_tools = built_in + mcp_tools

    return {
        "tools": all_tools,
        "count": len(all_tools),
    }
