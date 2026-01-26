"""
REST API server for AI Agent system.

Provides HTTP endpoints for:
- Running agents
- Health checks
- Metrics
- Agent management
"""

import asyncio
import dataclasses
import os
import time
import uuid
from datetime import datetime
from typing import Any

from sanic import Sanic, response
from sanic.request import Request
from sanic.response import JSONResponse

from .agents.base import TaskContext
from .core.agent_runner import (
    AgentRunner,
    ExecutionContext,
    _record_agent_run_complete,
    _record_agent_run_start,
    get_agent_registry,
    get_in_flight_runs,
    mark_shutdown_in_progress,
)
from .core.auth import AuthError, authenticate_request
from .core.config import get_config
from .core.logging import get_correlation_id, get_logger, set_correlation_id
from .core.metrics import get_metrics_collector
from .core.slack_hooks import SlackUpdateHooks, SlackUpdateState
from .integrations.slack_ui import build_investigation_dashboard

logger = get_logger(__name__)


def _build_session_id(context_data: dict) -> str | None:
    """
    Build session ID from context metadata to enable conversation resumption.

    Maps Slack threads and GitHub PRs to persistent sessions using SQLiteSession.
    Sessions are stored locally and persist within the pod's lifecycle.

    Args:
        context_data: Request context containing metadata

    Returns:
        session_id for resumable conversations (Slack threads, GitHub PRs)
        None for ephemeral conversations (API calls, web UI)
    """
    metadata = context_data.get("metadata", {})

    # Slack thread: Use thread_ts as unique identifier
    slack_meta = metadata.get("slack", {})
    if slack_meta.get("thread_ts"):
        channel_id = slack_meta.get("channel_id", "unknown")
        thread_ts = slack_meta["thread_ts"]
        # Format: slack_CHANNEL_THREADTS (underscores for dots)
        session_id = f"slack_{channel_id}_{thread_ts}".replace(".", "_")
        logger.info(
            "session_id_built_slack",
            session_id=session_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        return session_id

    # GitHub PR: Use repo + pr_number as unique identifier
    github_meta = metadata.get("github", {})
    if github_meta.get("pr_number"):
        repo = github_meta.get("repo", "unknown").replace("/", "_").replace("-", "_")
        pr_number = github_meta["pr_number"]
        # Format: github_REPO_prNUMBER
        session_id = f"github_{repo}_pr{pr_number}"
        logger.info(
            "session_id_built_github",
            session_id=session_id,
            repo=github_meta.get("repo"),
            pr_number=pr_number,
        )
        return session_id

    # No session for non-threaded conversations (ephemeral)
    logger.debug("no_session_id_ephemeral", trigger=metadata.get("trigger"))
    return None


# Config service URL for conversation mapping storage
CONFIG_SERVICE_URL = os.getenv(
    "CONFIG_SERVICE_URL", "http://incidentfox-config-service:8080"
)


async def _get_or_create_conversation_id(
    session_id: str,
    session_type: str,
    org_id: str | None = None,
    team_node_id: str | None = None,
) -> str | None:
    """
    Get existing OpenAI conversation_id for a session, or create a new conversation.

    This function:
    1. Checks config service for existing mapping (session_id → openai_conversation_id)
    2. If found, returns the stored OpenAI conversation_id
    3. If not found, creates a new OpenAI conversation and stores the mapping

    Args:
        session_id: Our session identifier (e.g., "slack_C0A8JDPU3SR_1768599264_192439")
        session_type: Type of session ("slack", "github", "api")
        org_id: Organization ID for the mapping
        team_node_id: Team node ID for the mapping

    Returns:
        OpenAI conversation_id if found/created, None on error
    """
    import httpx
    from openai import AsyncOpenAI

    try:
        # Step 1: Check config service for existing mapping
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/conversations/{session_id}",
                headers={"X-Internal-Service": "agent"},
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("found") and data.get("openai_conversation_id"):
                    logger.info(
                        "conversation_mapping_found",
                        session_id=session_id,
                        openai_conversation_id=data["openai_conversation_id"],
                    )
                    return data["openai_conversation_id"]

        # Step 2: No existing mapping - create a new OpenAI conversation
        logger.info("creating_new_openai_conversation", session_id=session_id)
        openai_client = AsyncOpenAI()
        conversation = await openai_client.conversations.create(items=[])
        openai_conversation_id = conversation.id

        logger.info(
            "openai_conversation_created",
            session_id=session_id,
            openai_conversation_id=openai_conversation_id,
        )

        # Step 3: Store the mapping in config service
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/conversations",
                headers={"X-Internal-Service": "agent"},
                json={
                    "session_id": session_id,
                    "openai_conversation_id": openai_conversation_id,
                    "session_type": session_type,
                    "org_id": org_id,
                    "team_node_id": team_node_id,
                },
            )

            if resp.status_code in (200, 201):
                logger.info(
                    "conversation_mapping_stored",
                    session_id=session_id,
                    openai_conversation_id=openai_conversation_id,
                )
            else:
                logger.warning(
                    "conversation_mapping_store_failed",
                    session_id=session_id,
                    status=resp.status_code,
                    body=resp.text[:200],
                )

        return openai_conversation_id

    except Exception as e:
        logger.error(
            "conversation_id_resolution_failed",
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
        return None


async def _store_conversation_mapping(
    session_id: str,
    openai_conversation_id: str,
    session_type: str,
    org_id: str | None = None,
    team_node_id: str | None = None,
) -> bool:
    """
    Store a conversation mapping in the config service.

    This is called after a successful agent run when a new conversation was created.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/conversations",
                headers={"X-Internal-Service": "agent"},
                json={
                    "session_id": session_id,
                    "openai_conversation_id": openai_conversation_id,
                    "session_type": session_type,
                    "org_id": org_id,
                    "team_node_id": team_node_id,
                },
            )

            if resp.status_code in (200, 201):
                logger.info(
                    "conversation_mapping_stored",
                    session_id=session_id,
                    openai_conversation_id=openai_conversation_id,
                )
                return True
            else:
                logger.warning(
                    "conversation_mapping_store_failed",
                    session_id=session_id,
                    status=resp.status_code,
                )
                return False

    except Exception as e:
        logger.error(
            "conversation_mapping_store_error",
            session_id=session_id,
            error=str(e),
        )
        return False


async def _create_mcp_servers_for_request(team_config, agent_name: str = None):
    """
    Create MCP servers for a request using AsyncExitStack pattern.

    Applies two levels of filtering:
    1. MCP-level: Only creates MCPs where mcp_config.enabled is True (default)
    2. Agent-level: Only creates MCPs where agents.{agent_name}.mcps.{mcp_id} is True

    Args:
        team_config: Team configuration with mcp_servers and agents
        agent_name: Name of the agent to filter MCPs for. If None, loads all enabled MCPs.

    Returns tuple of (stack, mcp_servers) where:
    - stack: AsyncExitStack that must be entered with 'async with'
    - mcp_servers: List of MCPServerStdio objects ready to pass to Agent()

    Usage:
        async with await _create_mcp_servers_for_request(team_config, "planner") as (stack, mcp_servers):
            agent = Agent(..., mcp_servers=mcp_servers)
            result = await Runner.run(agent, message)
    """
    from contextlib import AsyncExitStack

    from agents.mcp import MCPServerStdio

    # Check if team has MCP servers configured
    if (
        not team_config
        or not hasattr(team_config, "mcp_servers")
        or not team_config.mcp_servers
    ):
        return None, []

    # Get agent's MCP configuration if agent_name is provided
    agent_mcps_config = None
    if agent_name and hasattr(team_config, "get_agent_config"):
        agent_config = team_config.get_agent_config(agent_name)
        if agent_config:
            agent_mcps_config = getattr(agent_config, "mcps", None)
            # Also check if it's a dict with 'mcps' key
            if agent_mcps_config is None and hasattr(agent_config, "__getitem__"):
                try:
                    agent_mcps_config = agent_config.get("mcps")
                except (TypeError, AttributeError):
                    pass

    logger.info(
        "creating_mcp_servers_for_request",
        mcp_count=len(team_config.mcp_servers),
        agent_name=agent_name,
        agent_mcps_config=agent_mcps_config,
    )

    stack = AsyncExitStack()
    mcp_servers = []
    skipped_disabled = []
    skipped_not_in_agent = []

    try:
        # Create MCPServerStdio objects for each configured MCP server
        for mcp_id, mcp_config in team_config.mcp_servers.items():
            # Convert to dict if it's a Pydantic model
            if hasattr(mcp_config, "model_dump"):
                mcp_dict = mcp_config.model_dump()
            elif hasattr(mcp_config, "dict"):
                mcp_dict = mcp_config.dict()
            elif isinstance(mcp_config, dict):
                mcp_dict = dict(mcp_config)
            else:
                mcp_dict = mcp_config

            # Filter 1: Skip if MCP is explicitly disabled at team level
            if not mcp_dict.get("enabled", True):
                skipped_disabled.append(mcp_id)
                logger.debug(
                    "skipping_disabled_mcp",
                    mcp_id=mcp_id,
                    reason="mcp_config.enabled is False",
                )
                continue

            # Filter 2: Skip if agent has mcps config and this MCP is not enabled for the agent
            if agent_mcps_config is not None:
                # agent_mcps_config is a dict like {"azure-mcp": True, "github-mcp": False}
                # If the dict is empty {}, no MCPs are enabled for this agent
                # If the MCP is not in the dict or is False, skip it
                if not agent_mcps_config.get(mcp_id, False):
                    skipped_not_in_agent.append(mcp_id)
                    logger.debug(
                        "skipping_mcp_not_in_agent_config",
                        mcp_id=mcp_id,
                        agent_name=agent_name,
                        reason="not in agents.{agent}.mcps or set to False",
                    )
                    continue

            # Get timeout (default 120s for Azure operations)
            timeout_seconds = mcp_dict.get("timeout_seconds", 120)

            logger.info(
                "creating_mcp_server",
                mcp_id=mcp_id,
                name=mcp_dict.get("name", mcp_id),
                command=mcp_dict.get("command", "npx"),
                args=(
                    mcp_dict.get("args", [])[:3] if mcp_dict.get("args") else []
                ),  # First 3 args only
                env_keys=list(mcp_dict.get("env", {}).keys()),
                agent_name=agent_name,
            )

            # Create and start MCP server using AsyncExitStack
            server = await stack.enter_async_context(
                MCPServerStdio(
                    name=mcp_dict.get("name", mcp_id),
                    params={
                        "command": mcp_dict.get("command", "npx"),
                        "args": mcp_dict.get("args", []),
                        "env": mcp_dict.get("env", {}),
                    },
                    client_session_timeout_seconds=timeout_seconds,
                )
            )

            mcp_servers.append(server)
            logger.info(
                "mcp_server_created_for_request",
                mcp_id=mcp_id,
                name=mcp_dict.get("name", mcp_id),
                agent_name=agent_name,
            )

        logger.info(
            "mcp_servers_ready_for_request",
            server_count=len(mcp_servers),
            skipped_disabled=skipped_disabled,
            skipped_not_in_agent=skipped_not_in_agent,
            agent_name=agent_name,
        )

        return stack, mcp_servers

    except Exception as e:
        # Cleanup on error
        await stack.aclose()
        logger.error(
            "failed_to_create_mcp_servers_for_request", error=str(e), exc_info=True
        )
        raise


def _infer_tool_category(tool_name: str) -> str:
    """Infer tool category from tool name."""
    name_lower = tool_name.lower()

    if any(k in name_lower for k in ["k8s", "pod", "deployment", "kubernetes", "eks"]):
        return "kubernetes"
    elif any(k in name_lower for k in ["aws", "ec2", "s3", "lambda", "cloudwatch"]):
        return "aws"
    elif any(
        k in name_lower for k in ["github", "git", "pr", "pull_request", "commit"]
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
    elif any(k in name_lower for k in ["snowflake", "sql", "query", "database"]):
        return "data"
    elif any(k in name_lower for k in ["anomal", "correlate", "detect"]):
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
        for k in ["file", "read", "write", "filesystem", "directory", "path"]
    ):
        return "filesystem"
    elif any(k in name_lower for k in ["incident", "pagerduty"]):
        return "incident"
    elif any(k in name_lower for k in ["think", "llm", "agent"]):
        return "agent"
    else:
        return "other"


def create_app() -> Sanic:
    """Create and configure the Sanic application."""
    app = Sanic("ai-agent-api")

    # Configure timeouts for long-running agent requests
    app.config.REQUEST_TIMEOUT = 600  # 10 minutes
    app.config.RESPONSE_TIMEOUT = 600  # 10 minutes

    config = get_config()

    # CORS for development
    @app.middleware("request")
    async def add_cors_headers(request: Request):
        if request.method == "OPTIONS":
            return response.text(
                "",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-IncidentFox-Team-Token, X-Correlation-ID",
                },
            )

    @app.middleware("response")
    async def add_cors_response_headers(request: Request, resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    # Add correlation ID to all requests
    @app.middleware("request")
    async def add_correlation_id(request: Request):
        corr_id = request.headers.get("X-Correlation-ID") or get_correlation_id()
        set_correlation_id(corr_id)
        request.ctx.correlation_id = corr_id

    # Authenticate requests
    @app.middleware("request")
    async def auth_middleware(request: Request):
        # Skip auth for health and metrics endpoints
        if request.path in ["/health", "/ready", "/metrics", "/mcp/health"]:
            return

        try:
            auth_context = authenticate_request(request)
            request.ctx.auth = auth_context
        except AuthError as e:
            return response.json(
                {"error": "Authentication failed", "message": str(e)},
                status=401,
            )

    # Log all requests
    @app.middleware("request")
    async def log_request(request: Request):
        logger.info(
            "api_request",
            method=request.method,
            path=request.path,
            correlation_id=request.ctx.correlation_id,
            authenticated=getattr(request.ctx, "auth", {}).get("authenticated", False),
        )

    # Health check
    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        """Health check endpoint."""
        registry = get_agent_registry()

        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "agents": {
                "total": len(registry.list_agents()),
                "names": registry.list_agents(),
            },
        }

        # Check config service if enabled
        if config.use_config_service:
            try:
                from .core.config_service import get_config_service_client

                # In shared-runtime mode there may be no process-level team token, so skip.
                if not os.getenv("INCIDENTFOX_TEAM_TOKEN"):
                    raise RuntimeError(
                        "INCIDENTFOX_TEAM_TOKEN not set (shared runtime)"
                    )
                client = get_config_service_client()
                identity = client.fetch_auth_identity()
                health_status["config_service"] = {
                    "status": "connected",
                    "org_id": identity.org_id,
                    "team_id": identity.team_node_id,
                }
            except Exception as e:
                health_status["config_service"] = {
                    "status": "error",
                    "error": str(e),
                }

        return response.json(health_status)

    # Readiness check
    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Readiness check - are agents initialized?"""
        registry = get_agent_registry()
        agents = registry.list_agents()

        is_ready = len(agents) > 0
        status_code = 200 if is_ready else 503

        return response.json(
            {
                "ready": is_ready,
                "agents_count": len(agents),
            },
            status=status_code,
        )

    # MCP health check
    @app.get("/mcp/health")
    async def mcp_health(request: Request) -> JSONResponse:
        """MCP servers health check endpoint."""
        try:
            from .integrations.mcp.client import get_mcp_client

            mcp_client = get_mcp_client()

            # Run health checks on all servers
            health_results = await mcp_client.check_all_health()

            # Calculate overall health
            all_healthy = (
                all(h["healthy"] for h in health_results.values())
                if health_results
                else True
            )
            healthy_count = sum(1 for h in health_results.values() if h["healthy"])

            status_code = 200 if all_healthy else 503

            return response.json(
                {
                    "overall_healthy": all_healthy,
                    "total_servers": len(health_results),
                    "healthy_servers": healthy_count,
                    "servers": health_results,
                },
                status=status_code,
            )

        except Exception as e:
            logger.error("mcp_health_check_error", error=str(e))
            return response.json(
                {
                    "overall_healthy": False,
                    "error": str(e),
                },
                status=503,
            )

    # Metrics endpoint (Prometheus format)
    @app.get("/metrics")
    async def metrics(request: Request):
        """Prometheus metrics endpoint."""
        metrics_collector = get_metrics_collector()
        metrics_data = metrics_collector.get_prometheus_metrics()
        return response.text(metrics_data.decode("utf-8"))

    # List agents
    @app.get("/agents")
    async def list_agents(request: Request) -> JSONResponse:
        """List all available agents."""
        registry = get_agent_registry()
        agents = registry.list_agents()

        return response.json(
            {
                "agents": agents,
                "count": len(agents),
            }
        )

    # Run agent
    @app.post("/agents/<agent_name>/run")
    async def run_agent(request: Request, agent_name: str) -> JSONResponse:
        """
        Run a specific agent.

        Request body:
        {
            "message": "Your task description",
            "context": {
                "user_id": "optional",
                "metadata": {}
            },
            "max_turns": 10,
            "timeout": 300
        }
        """
        registry = get_agent_registry()

        # Resolve per-request team config (shared runtime) if provided.
        team_config = None
        team_config_hash = None
        auth_identity = None
        if config.use_config_service:
            team_token = request.headers.get("X-IncidentFox-Team-Token")
            if team_token:
                from .core.config_service import get_config_service_client

                client = get_config_service_client()

                # Fetch team config and identity
                team_config = client.fetch_effective_config(team_token=team_token)
                auth_identity = client.fetch_auth_identity(team_token=team_token)
                team_config_hash = str(hash(team_config.model_dump_json()))
                # MVP KB integration: fetch lightweight KB matches for the incoming message
                # and inject into request metadata so the agent can use it.
                try:
                    import httpx

                    cfg_base = os.getenv("CONFIG_BASE_URL", "").rstrip("/")
                    if cfg_base:
                        with httpx.Client(timeout=5.0) as c:
                            q = str(request.json.get("message") or "").strip()
                            r = c.get(
                                f"{cfg_base}/api/v1/config/me/knowledge/search",
                                headers={"Authorization": f"Bearer {team_token}"},
                                params={"q": q, "limit": 10},
                            )
                            if r.status_code == 200:
                                kb = r.json()
                                # Merge into metadata (best-effort)
                                ctx_obj = request.json.get("context") or {}
                                meta = ctx_obj.get("metadata") or {}
                                meta["knowledge_base_edges"] = kb.get("results") or []
                                ctx_obj["metadata"] = meta
                                request.json["context"] = ctx_obj
                            r2 = c.get(
                                f"{cfg_base}/api/v1/config/me/knowledge/docs/search",
                                headers={"Authorization": f"Bearer {team_token}"},
                                params={"q": q, "limit": 8},
                            )
                            if r2.status_code == 200:
                                docs = r2.json()
                                ctx_obj = request.json.get("context") or {}
                                meta = ctx_obj.get("metadata") or {}
                                meta["knowledge_base_docs"] = docs.get("results") or []
                                ctx_obj["metadata"] = meta
                                request.json["context"] = ctx_obj
                except Exception:
                    # Never fail agent execution due to KB enrichment
                    pass

        runner = registry.get_runner(
            agent_name,
            team_config_hash=team_config_hash,
            factory_kwargs={"team_config": team_config} if team_config else None,
        )

        # If agent not found in registry, try creating it dynamically from team config
        if not runner and team_config:
            try:
                from .agents.registry import create_generic_agent_from_config

                # Check if agent exists in team config
                agent_config = team_config.get_agent_config(agent_name)

                if agent_config and agent_config.enabled:
                    # Create agent dynamically
                    agent = create_generic_agent_from_config(
                        agent_name, team_config=team_config
                    )

                    # Get max_retries from config
                    max_retries = agent_config.max_retries or 3

                    # Create runner
                    runner = AgentRunner(agent, max_retries=max_retries)

                    logger.info(
                        "dynamic_agent_created",
                        agent_name=agent_name,
                        team_config_hash=team_config_hash,
                        runner_is_none=runner is None,
                    )
                else:
                    logger.warning(
                        "agent_not_in_config",
                        agent_name=agent_name,
                        has_config=agent_config is not None,
                        enabled=agent_config.enabled if agent_config else None,
                    )
            except Exception as e:
                logger.error(
                    "dynamic_agent_creation_failed",
                    agent_name=agent_name,
                    error=str(e),
                    exc_info=True,
                )

        if not runner:
            logger.error(
                "runner_is_none_returning_404",
                agent_name=agent_name,
                team_config_hash=team_config_hash,
                had_team_config=team_config is not None,
            )
            return response.json(
                {
                    "error": f"Agent '{agent_name}' not found",
                    "available_agents": registry.list_agents(),
                },
                status=404,
            )

        logger.info(
            "runner_found_proceeding",
            agent_name=agent_name,
            runner_type=type(runner).__name__,
        )

        try:
            # Parse request
            data = request.json
            message = data.get("message")
            context_data = data.get("context", {})
            timeout = data.get("timeout")
            max_turns = data.get("max_turns")

            # Output destinations (new multi-destination system)
            output_destinations_raw = data.get("output_destinations")
            # Backwards compatibility: convert slack_context to output_destinations
            slack_context_data = data.get("slack_context")

            if not message:
                return response.json(
                    {"error": "Missing 'message' in request body"},
                    status=400,
                )

            # Extract and format local_context from CLI
            local_context = context_data.get("local_context")
            if local_context:
                from .prompts import format_local_context

                context_preamble = format_local_context(local_context)
                if context_preamble:
                    # Prepend local context to the user message
                    message = f"{context_preamble}\n## User Query\n\n{message}"
                    logger.info(
                        "local_context_injected_non_stream",
                        has_k8s=bool(local_context.get("kubernetes")),
                        has_git=bool(local_context.get("git")),
                        has_aws=bool(local_context.get("aws")),
                        has_key_context=bool(local_context.get("key_context")),
                    )

            # Inject user context (runtime metadata + team contextual info)
            # This allows context to flow naturally to sub-agents when delegating
            if team_config:
                from .prompts import build_user_context

                # Extract team context dict from config
                team_context_dict = None
                if hasattr(team_config, "model_dump"):
                    team_context_dict = team_config.model_dump()
                elif isinstance(team_config, dict):
                    team_context_dict = team_config

                user_context = build_user_context(
                    timestamp=datetime.now().isoformat(),
                    org_id=(auth_identity.org_id if auth_identity else None),
                    team_id=(auth_identity.team_node_id if auth_identity else None),
                    environment=context_data.get("metadata", {}).get("environment"),
                    incident_id=context_data.get("metadata", {}).get("incident_id"),
                    alert_source=context_data.get("metadata", {}).get("alert_source"),
                    team_config=team_context_dict,
                )
                if user_context:
                    message = f"{user_context}\n## Task\n\n{message}"
                    logger.info(
                        "user_context_injected_non_stream",
                        has_team_config=True,
                        context_length=len(user_context),
                    )

            # Parse message for multimodal content (embedded images)
            from .core.multimodal import (
                get_message_preview,
                parse_multimodal_message,
            )

            parsed_message = parse_multimodal_message(message)
            message_preview = get_message_preview(parsed_message, max_length=100)
            is_multimodal = isinstance(parsed_message, list)

            # Build output destinations list
            output_destinations = []
            if output_destinations_raw:
                from .core.output_handler import parse_output_destinations

                output_destinations = parse_output_destinations(output_destinations_raw)
            elif slack_context_data:
                # Backwards compatibility: convert slack_context to output destination
                from .core.output_handler import OutputDestination

                if slack_context_data.get("channel_id"):
                    output_destinations = [
                        OutputDestination(
                            type="slack",
                            config={
                                "channel_id": slack_context_data.get("channel_id"),
                                "thread_ts": slack_context_data.get("thread_ts"),
                                "user_id": slack_context_data.get("user_id"),
                                "bot_token": slack_context_data.get("bot_token"),
                            },
                        )
                    ]

            # Log output destinations for debugging
            logger.info(
                "agent_run_output_destinations_parsed",
                agent_name=agent_name,
                correlation_id=request.ctx.correlation_id,
                has_output_destinations_raw=bool(output_destinations_raw),
                has_slack_context=bool(slack_context_data),
                destination_count=len(output_destinations),
                destination_types=(
                    [d.type for d in output_destinations] if output_destinations else []
                ),
            )

            # If output destinations provided, use the output handler system
            if output_destinations:
                from .core.output_handler import (
                    post_initial_to_destinations,
                    post_to_destinations,
                )

                # Get the raw agent from the runner
                base_agent = runner.agent

                display_name = agent_name.replace("_", " ").title()

                logger.info(
                    "running_agent_with_output_destinations",
                    agent_name=agent_name,
                    destinations=[d.type for d in output_destinations],
                    correlation_id=request.ctx.correlation_id,
                )

                start_time = time.time()
                run_id = str(uuid.uuid4())  # Generate unique run ID for tracking

                # Get org/team from auth context for recording
                org_id = auth_identity.org_id if auth_identity else ""
                team_node_id = auth_identity.team_node_id if auth_identity else ""

                # Determine trigger source from output destinations
                trigger_source = "api"
                if output_destinations:
                    dest_types = [d.type for d in output_destinations]
                    if "slack" in dest_types:
                        trigger_source = "slack"
                    elif (
                        "github_pr_comment" in dest_types
                        or "github_issue_comment" in dest_types
                    ):
                        trigger_source = "github"

                # Record agent run start (fire and forget)
                asyncio.create_task(
                    _record_agent_run_start(
                        run_id=run_id,
                        agent_name=agent_name,
                        correlation_id=request.ctx.correlation_id,
                        trigger_source=trigger_source,
                        trigger_message=message[:500] if message else "",
                        org_id=org_id,
                        team_node_id=team_node_id,
                    )
                )

                # Post initial "working" messages
                message_ids = await post_initial_to_destinations(
                    destinations=output_destinations,
                    task_description=message,
                    agent_name=display_name,
                )

                # Set up Slack progressive dashboard hooks if Slack destination exists
                slack_hooks = None
                slack_dest = None
                for dest in output_destinations:
                    if dest.type == "slack":
                        slack_dest = dest
                        break

                if slack_dest and message_ids.get("slack"):
                    try:
                        # Get Slack client
                        slack_token = slack_dest.config.get("bot_token") or os.getenv(
                            "SLACK_BOT_TOKEN", ""
                        )
                        if slack_token:
                            try:
                                from slack_sdk.web.async_client import AsyncWebClient

                                slack_client = AsyncWebClient(token=slack_token)
                            except ImportError:
                                slack_client = None

                            if slack_client:
                                channel_id = slack_dest.config.get("channel_id")
                                message_ts = message_ids.get("slack")
                                thread_ts = slack_dest.config.get("thread_ts")

                                # Create initial dashboard with empty phases
                                # (phases will be discovered dynamically as tools run)
                                initial_blocks = build_investigation_dashboard(
                                    phase_status={},
                                    title=f"{display_name} Investigation",
                                    context_text=f"_Investigating: {message[:100]}{'...' if len(message) > 100 else ''}_",
                                    phases={},  # Empty - will be populated dynamically
                                )

                                # Update the initial message with dashboard format
                                await slack_client.chat_update(
                                    channel=channel_id,
                                    ts=message_ts,
                                    text="Investigation in progress...",
                                    blocks=initial_blocks,
                                )

                                # Create hooks for progressive updates
                                slack_state = SlackUpdateState(
                                    channel_id=channel_id,
                                    message_ts=message_ts,
                                    thread_ts=thread_ts,
                                    title=f"{display_name} Investigation",
                                )
                                slack_hooks = SlackUpdateHooks(
                                    state=slack_state,
                                    slack_client=slack_client,
                                )

                                logger.info(
                                    "slack_hooks_initialized",
                                    channel_id=channel_id,
                                    message_ts=message_ts,
                                )
                    except Exception as e:
                        logger.warning(
                            "slack_hooks_init_failed",
                            error=str(e),
                            exc_info=True,
                        )
                        slack_hooks = None

                # Set team execution context for integration access
                from .core.execution_context import (
                    clear_execution_context,
                    set_execution_context,
                    set_execution_hooks,
                )

                if auth_identity and team_config:
                    set_execution_context(
                        org_id=auth_identity.org_id,
                        team_node_id=auth_identity.team_node_id,
                        team_config=(
                            team_config.model_dump()
                            if hasattr(team_config, "model_dump")
                            else team_config
                        ),
                    )

                # Store hooks in context for propagation to subagents
                # This enables tool calls from subagents to appear in Slack dashboard
                if slack_hooks:
                    set_execution_hooks(slack_hooks)

                # Create MCP servers if team has them configured (filtered by agent's mcps config)
                stack, mcp_servers = await _create_mcp_servers_for_request(
                    team_config, agent_name
                )

                logger.info(
                    "mcp_servers_created_starting_agent_execution",
                    agent_name=agent_name,
                    mcp_count=len(mcp_servers) if mcp_servers else 0,
                    correlation_id=request.ctx.correlation_id,
                )

                try:
                    # Build session ID and look up/create OpenAI conversation_id
                    session_id = _build_session_id(context_data)
                    conversation_id = None

                    if session_id:
                        # Determine session type from the session_id format
                        session_type = (
                            "slack"
                            if session_id.startswith("slack_")
                            else "github" if session_id.startswith("github_") else "api"
                        )

                        # Look up existing OpenAI conversation_id from config service
                        conversation_id = await _get_or_create_conversation_id(
                            session_id=session_id,
                            session_type=session_type,
                            org_id=auth_identity.org_id if auth_identity else None,
                            team_node_id=(
                                auth_identity.team_node_id if auth_identity else None
                            ),
                        )

                        if conversation_id:
                            logger.info(
                                "conversation_id_resolved",
                                session_id=session_id,
                                conversation_id=conversation_id,
                                agent_name=agent_name,
                            )

                    # If we have MCP servers, create agent with them
                    # Otherwise use the cached agent
                    if stack and mcp_servers:
                        async with stack:
                            # Create fresh agent with MCP servers
                            from agents import Agent

                            agent_with_mcp = Agent(
                                name=base_agent.name,
                                instructions=base_agent.instructions,
                                model=base_agent.model,
                                model_settings=(
                                    base_agent.model_settings
                                    if hasattr(base_agent, "model_settings")
                                    else None
                                ),
                                tools=(
                                    base_agent.tools
                                    if hasattr(base_agent, "tools")
                                    else []
                                ),
                                output_type=(
                                    base_agent.output_type
                                    if hasattr(base_agent, "output_type")
                                    else None
                                ),
                                mcp_servers=mcp_servers,  # Add MCP servers!
                            )

                            logger.info(
                                "agent_created_with_mcp_servers",
                                agent_name=agent_name,
                                mcp_count=len(mcp_servers),
                            )

                            # Run agent
                            from agents import Runner

                            agent_runner = Runner()

                            logger.info(
                                "starting_agent_execution_with_mcp",
                                agent_name=agent_name,
                                message_preview=message_preview,
                                max_turns=max_turns or 100,
                                timeout=timeout or 600,
                                has_conversation_id=conversation_id is not None,
                                session_id=session_id,
                                correlation_id=request.ctx.correlation_id,
                                is_multimodal=is_multimodal,
                                has_slack_hooks=slack_hooks is not None,
                            )

                            agent_result = await asyncio.wait_for(
                                agent_runner.run(
                                    agent_with_mcp,
                                    parsed_message,
                                    conversation_id=conversation_id,  # Pass conversation_id directly
                                    max_turns=max_turns or 100,
                                    hooks=slack_hooks,  # Progressive Slack updates
                                ),
                                timeout=timeout or 600,
                            )

                            # Store the conversation_id mapping if this was a new conversation
                            if (
                                session_id
                                and not conversation_id
                                and hasattr(agent_result, "last_response_id")
                            ):
                                # Extract conversation_id from the result (OpenAI creates it automatically)
                                new_conv_id = getattr(
                                    agent_result, "conversation_id", None
                                )
                                if new_conv_id:
                                    await _store_conversation_mapping(
                                        session_id=session_id,
                                        openai_conversation_id=new_conv_id,
                                        session_type=session_type,
                                        org_id=(
                                            auth_identity.org_id
                                            if auth_identity
                                            else None
                                        ),
                                        team_node_id=(
                                            auth_identity.team_node_id
                                            if auth_identity
                                            else None
                                        ),
                                    )

                            logger.info(
                                "agent_execution_completed_with_mcp",
                                agent_name=agent_name,
                                has_result=agent_result is not None,
                                correlation_id=request.ctx.correlation_id,
                            )
                    else:
                        # No MCP servers, use cached agent
                        from agents import Runner

                        agent_runner = Runner()

                        logger.info(
                            "starting_agent_execution_without_mcp",
                            agent_name=agent_name,
                            message_preview=message_preview,
                            max_turns=max_turns or 100,
                            timeout=timeout or 600,
                            has_conversation_id=conversation_id is not None,
                            session_id=session_id,
                            correlation_id=request.ctx.correlation_id,
                            is_multimodal=is_multimodal,
                            has_slack_hooks=slack_hooks is not None,
                        )

                        agent_result = await asyncio.wait_for(
                            agent_runner.run(
                                base_agent,
                                parsed_message,
                                conversation_id=conversation_id,  # Pass conversation_id directly
                                max_turns=max_turns or 100,
                                hooks=slack_hooks,  # Progressive Slack updates
                            ),
                            timeout=timeout or 600,
                        )

                        # Store the conversation_id mapping if this was a new conversation
                        if session_id and not conversation_id:
                            # For new conversations, we need to create one first via OpenAI API
                            # The SDK should store it - let's check the result
                            new_conv_id = getattr(agent_result, "conversation_id", None)
                            if new_conv_id:
                                session_type = (
                                    "slack"
                                    if session_id.startswith("slack_")
                                    else (
                                        "github"
                                        if session_id.startswith("github_")
                                        else "api"
                                    )
                                )
                                await _store_conversation_mapping(
                                    session_id=session_id,
                                    openai_conversation_id=new_conv_id,
                                    session_type=session_type,
                                    org_id=(
                                        auth_identity.org_id if auth_identity else None
                                    ),
                                    team_node_id=(
                                        auth_identity.team_node_id
                                        if auth_identity
                                        else None
                                    ),
                                )

                        logger.info(
                            "agent_execution_completed_without_mcp",
                            agent_name=agent_name,
                            has_result=agent_result is not None,
                            correlation_id=request.ctx.correlation_id,
                        )

                    duration = time.time() - start_time
                    output = getattr(agent_result, "final_output", None) or getattr(
                        agent_result, "output", None
                    )

                    # Finalize Slack hooks if they were used (rich dashboard update)
                    slack_finalized = False
                    if slack_hooks:
                        try:
                            # Extract findings from output for the dashboard
                            findings = None
                            confidence = None
                            if isinstance(output, dict):
                                findings = output.get("summary") or output.get("result")
                                confidence = output.get("confidence")
                            elif hasattr(output, "summary"):
                                findings = output.summary
                                confidence = getattr(output, "confidence", None)
                            elif isinstance(output, str):
                                findings = output

                            await slack_hooks.finalize(
                                findings=findings,
                                confidence=confidence,
                            )
                            slack_finalized = True
                            logger.info(
                                "slack_hooks_finalized",
                                has_findings=findings is not None,
                            )
                        except Exception as e:
                            logger.warning(
                                "slack_hooks_finalize_failed",
                                error=str(e),
                                exc_info=True,
                            )

                    # Post final results to non-Slack destinations
                    # (Slack is already handled by hooks.finalize() if slack_finalized)
                    non_slack_destinations = [
                        d for d in output_destinations if d.type != "slack"
                    ]
                    # If Slack finalization failed, include it in post_to_destinations
                    if not slack_finalized:
                        non_slack_destinations = output_destinations

                    results = await post_to_destinations(
                        destinations=non_slack_destinations,
                        output=output,
                        success=True,
                        duration_seconds=duration,
                        agent_name=display_name,
                        message_ids=message_ids,
                    )

                    # Add Slack to results if finalized via hooks
                    if slack_finalized:
                        from .core.output_handler import OutputResult

                        results.append(
                            OutputResult(
                                success=True,
                                destination_type="slack",
                                message_id=message_ids.get("slack"),
                            )
                        )

                    # Record agent run completion
                    output_summary = ""
                    if isinstance(output, dict) and "summary" in output:
                        output_summary = str(output["summary"])[:1000]
                    elif isinstance(output, str):
                        output_summary = output[:1000]
                    asyncio.create_task(
                        _record_agent_run_complete(
                            run_id=run_id,
                            status="completed",
                            duration_seconds=duration,
                            output_summary=output_summary,
                            tool_calls_count=0,  # Non-streaming doesn't track tool calls
                        )
                    )

                    return response.json(
                        {
                            "success": True,
                            "agent": agent_name,
                            "correlation_id": request.ctx.correlation_id,
                            "output_mode": "destinations",
                            "destinations_posted": [
                                r.destination_type for r in results if r.success
                            ],
                            "duration_seconds": round(duration, 2),
                        },
                        status=200,
                    )

                except TimeoutError:
                    duration = time.time() - start_time
                    error_msg = f"Agent timed out after {timeout or 600}s"

                    # If Slack hooks exist, mark phases as failed
                    if slack_hooks:
                        try:
                            for phase in slack_hooks.state.phase_status:
                                if slack_hooks.state.phase_status[phase] == "running":
                                    slack_hooks.state.phase_status[phase] = "failed"
                        except Exception:
                            pass

                    await post_to_destinations(
                        destinations=output_destinations,
                        output=None,
                        success=False,
                        error=error_msg,
                        duration_seconds=duration,
                        agent_name=display_name,
                        message_ids=message_ids,
                    )

                    # Record timeout
                    asyncio.create_task(
                        _record_agent_run_complete(
                            run_id=run_id,
                            status="timeout",
                            duration_seconds=duration,
                            error_message=error_msg,
                            tool_calls_count=0,
                        )
                    )

                    return response.json(
                        {
                            "success": False,
                            "agent": agent_name,
                            "correlation_id": request.ctx.correlation_id,
                            "output_mode": "destinations",
                            "error": error_msg,
                        },
                        status=200,
                    )

                except Exception as e:
                    duration = time.time() - start_time
                    error_msg = str(e)

                    # If Slack hooks exist, mark phases as failed
                    if slack_hooks:
                        try:
                            for phase in slack_hooks.state.phase_status:
                                if slack_hooks.state.phase_status[phase] == "running":
                                    slack_hooks.state.phase_status[phase] = "failed"
                        except Exception:
                            pass

                    await post_to_destinations(
                        destinations=output_destinations,
                        output=None,
                        success=False,
                        error=error_msg,
                        duration_seconds=duration,
                        agent_name=display_name,
                        message_ids=message_ids,
                    )

                    # Record failure
                    asyncio.create_task(
                        _record_agent_run_complete(
                            run_id=run_id,
                            status="failed",
                            duration_seconds=duration,
                            error_message=error_msg[:500],
                            tool_calls_count=0,
                        )
                    )

                    return response.json(
                        {
                            "success": False,
                            "agent": agent_name,
                            "correlation_id": request.ctx.correlation_id,
                            "output_mode": "destinations",
                            "error": error_msg,
                        },
                        status=200,
                    )
                finally:
                    # Always clear execution context after agent run
                    if auth_identity and team_config:
                        clear_execution_context()

            # No output destinations - agent runs but output is returned in response only
            # (no Slack/GitHub/etc posting)
            logger.info(
                "running_agent_without_output_destinations",
                agent_name=agent_name,
                correlation_id=request.ctx.correlation_id,
                note="Agent will run but output will not be posted to external destinations. "
                "Configure notifications.incidentio_output.slack_channel_id or "
                "notifications.default_slack_channel_id in team config to enable Slack output.",
            )

            # Set team execution context for integration access
            from .core.execution_context import (
                clear_execution_context,
                set_execution_context,
            )

            if auth_identity and team_config:
                set_execution_context(
                    org_id=auth_identity.org_id,
                    team_node_id=auth_identity.team_node_id,
                    team_config=(
                        team_config.model_dump()
                        if hasattr(team_config, "model_dump")
                        else team_config
                    ),
                )

            # Create MCP servers if team has them configured (filtered by agent's mcps config)
            stack, mcp_servers = await _create_mcp_servers_for_request(
                team_config, agent_name
            )

            try:
                # If we have MCP servers, create a fresh AgentRunner with the agent
                # Otherwise use the cached runner
                if stack and mcp_servers:
                    async with stack:
                        # Get base agent properties
                        base_agent = runner.agent

                        # Create fresh agent with MCP servers
                        from agents import Agent

                        agent_with_mcp = Agent(
                            name=base_agent.name,
                            instructions=base_agent.instructions,
                            model=base_agent.model,
                            model_settings=(
                                base_agent.model_settings
                                if hasattr(base_agent, "model_settings")
                                else None
                            ),
                            tools=(
                                base_agent.tools if hasattr(base_agent, "tools") else []
                            ),
                            output_type=(
                                base_agent.output_type
                                if hasattr(base_agent, "output_type")
                                else None
                            ),
                            mcp_servers=mcp_servers,  # Add MCP servers!
                        )

                        logger.info(
                            "agent_created_with_mcp_servers",
                            agent_name=agent_name,
                            mcp_count=len(mcp_servers),
                        )

                        # Create fresh AgentRunner with the MCP-enabled agent
                        mcp_runner = AgentRunner(
                            agent_with_mcp, max_retries=runner.max_retries
                        )

                        # Create context
                        task_context = TaskContext(
                            request_id=request.ctx.correlation_id,
                            task_description=message,
                            user_id=context_data.get("user_id"),
                            metadata=context_data.get("metadata", {}),
                        )

                        # Create execution context
                        exec_context = ExecutionContext(
                            correlation_id=request.ctx.correlation_id,
                            metadata=context_data.get("metadata", {}),
                            timeout=timeout,
                            max_turns=max_turns if isinstance(max_turns, int) else None,
                        )

                        # Run agent
                        logger.info(
                            "running_agent_with_mcp",
                            agent_name=agent_name,
                            message_preview=message_preview,
                            correlation_id=request.ctx.correlation_id,
                            is_multimodal=is_multimodal,
                        )

                        result = await mcp_runner.run(
                            context=task_context,
                            user_message=parsed_message,
                            execution_context=exec_context,
                        )
                else:
                    # No MCP servers, use cached runner
                    # Create context
                    task_context = TaskContext(
                        request_id=request.ctx.correlation_id,
                        task_description=message,
                        user_id=context_data.get("user_id"),
                        metadata=context_data.get("metadata", {}),
                    )

                    # Create execution context
                    exec_context = ExecutionContext(
                        correlation_id=request.ctx.correlation_id,
                        metadata=context_data.get("metadata", {}),
                        timeout=timeout,
                        max_turns=max_turns if isinstance(max_turns, int) else None,
                    )

                    # Run agent
                    logger.info(
                        "running_agent",
                        agent_name=agent_name,
                        message_preview=message_preview,
                        correlation_id=request.ctx.correlation_id,
                        is_multimodal=is_multimodal,
                    )

                    result = await runner.run(
                        context=task_context,
                        user_message=parsed_message,
                        execution_context=exec_context,
                    )
            finally:
                # Always clear execution context after agent run
                if auth_identity and team_config:
                    clear_execution_context()

            def _jsonable(v: Any) -> Any:
                """Best-effort conversion to JSON-serializable primitives."""
                if v is None or isinstance(v, (str, int, float, bool)):
                    return v
                if isinstance(v, (list, tuple)):
                    return [_jsonable(x) for x in v]
                if isinstance(v, dict):
                    return {str(k): _jsonable(val) for k, val in v.items()}
                if dataclasses.is_dataclass(v):
                    return _jsonable(dataclasses.asdict(v))
                model_dump = getattr(v, "model_dump", None)  # pydantic v2
                if callable(model_dump):
                    return _jsonable(model_dump())
                return str(v)

            # Format response
            response_data = {
                "success": result.success,
                "agent": agent_name,
                "correlation_id": result.correlation_id,
                "duration_seconds": result.duration_seconds,
            }

            if result.success:
                response_data["output"] = _jsonable(result.output)
                response_data["token_usage"] = _jsonable(result.token_usage)
            else:
                response_data["error"] = result.error

            # Always return 200 for successfully-processed requests.
            # The `success` field indicates the logical outcome.
            # This prevents clients from treating handled failures (e.g. MaxTurnsExceeded)
            # as server errors.
            return response.json(response_data, status=200)

        except Exception as e:
            logger.error(
                "agent_execution_failed",
                agent_name=agent_name,
                error=str(e),
                correlation_id=request.ctx.correlation_id,
                exc_info=True,
            )

            return response.json(
                {
                    "error": str(e),
                    "agent": agent_name,
                    "correlation_id": request.ctx.correlation_id,
                },
                status=500,
            )

    # Run agent with SSE streaming
    @app.post("/agents/<agent_name>/run/stream")
    async def run_agent_stream(request: Request, agent_name: str):
        """
        Run a specific agent with Server-Sent Events (SSE) streaming.

        Returns real-time events as the agent executes, including:
        - agent_started: Agent execution has begun
        - tool_started: A tool call is starting
        - tool_completed: A tool call has finished
        - text_delta: Streaming text output (optional)
        - agent_completed: Final result

        Request body (same as /agents/<agent_name>/run):
        {
            "message": "Your task description",
            "context": {},
            "max_turns": 10,
            "timeout": 300
        }

        Response: SSE stream with events in format:
        event: <event_type>
        data: <json_data>
        """
        import json

        from sanic.response import ResponseStream

        registry = get_agent_registry()

        # Resolve per-request team config if provided (best-effort, don't fail if unavailable)
        team_config = None
        auth_identity = None
        if config.use_config_service:
            team_token = request.headers.get("X-IncidentFox-Team-Token")
            if team_token:
                try:
                    from .core.config_service import get_config_service_client

                    client = get_config_service_client()
                    team_config = client.fetch_effective_config(team_token=team_token)
                    auth_identity = client.fetch_auth_identity(team_token=team_token)
                except Exception as e:
                    logger.warning(
                        "stream_config_fetch_failed",
                        error=str(e),
                        agent_name=agent_name,
                    )
                    # Continue without team config - use default agent

        # Get the agent
        runner = registry.get_runner(
            agent_name,
            team_config_hash=(
                str(hash(team_config.model_dump_json())) if team_config else None
            ),
            factory_kwargs={"team_config": team_config} if team_config else None,
        )

        if not runner:
            return response.json(
                {
                    "error": f"Agent '{agent_name}' not found",
                    "available_agents": registry.list_agents(),
                },
                status=404,
            )

        try:
            data = request.json
            message = data.get("message")
            context_data = data.get("context", {})
            timeout = data.get("timeout", 300)
            max_turns = data.get("max_turns", 20)
            # Support conversation chaining - if provided, continues from previous response
            previous_response_id = data.get("previous_response_id")

            if not message:
                return response.json(
                    {"error": "Missing 'message' in request body"},
                    status=400,
                )

            # Extract and format local_context from CLI
            local_context = context_data.get("local_context")
            if local_context:
                from .prompts import format_local_context

                context_preamble = format_local_context(local_context)
                if context_preamble:
                    # Prepend local context to the user message
                    message = f"{context_preamble}\n## User Query\n\n{message}"
                    logger.info(
                        "local_context_injected",
                        has_k8s=bool(local_context.get("kubernetes")),
                        has_git=bool(local_context.get("git")),
                        has_aws=bool(local_context.get("aws")),
                        has_key_context=bool(local_context.get("key_context")),
                    )

            # Inject user context (runtime metadata + team contextual info)
            # This allows context to flow naturally to sub-agents when delegating
            if team_config:
                from .prompts import build_user_context

                # Extract team context dict from config
                team_context_dict = None
                if hasattr(team_config, "model_dump"):
                    team_context_dict = team_config.model_dump()
                elif isinstance(team_config, dict):
                    team_context_dict = team_config

                user_context = build_user_context(
                    timestamp=datetime.now().isoformat(),
                    org_id=(auth_identity.org_id if auth_identity else None),
                    team_id=(auth_identity.team_node_id if auth_identity else None),
                    environment=context_data.get("metadata", {}).get("environment"),
                    incident_id=context_data.get("metadata", {}).get("incident_id"),
                    alert_source=context_data.get("metadata", {}).get("alert_source"),
                    team_config=team_context_dict,
                )
                if user_context:
                    message = f"{user_context}\n## Task\n\n{message}"
                    logger.info(
                        "user_context_injected_stream",
                        has_team_config=True,
                    )

            async def stream_events(response_stream):
                """Generator that yields SSE events during agent execution."""
                from agents import Runner

                from .core.multimodal import (
                    get_message_preview,
                    parse_multimodal_message,
                )
                from .core.stream_events import (
                    EventStreamRegistry,
                    set_current_stream_id,
                )

                start_time = time.time()
                correlation_id = request.ctx.correlation_id
                run_id = str(uuid.uuid4())  # Generate unique run ID for tracking
                tool_calls_count = 0
                # Track response_id for chaining follow-up queries
                current_response_id = previous_response_id

                # Helper to format SSE event
                def sse_event(event_type: str, data: dict) -> str:
                    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

                # Create event stream for sub-agent event propagation
                stream_id = correlation_id
                subagent_queue = EventStreamRegistry.create_stream(stream_id)
                set_current_stream_id(stream_id)

                # Get org/team from auth context
                org_id = auth_identity.org_id if auth_identity else ""
                team_node_id = auth_identity.team_node_id if auth_identity else ""

                # Record agent run start (fire and forget, don't block streaming)
                asyncio.create_task(
                    _record_agent_run_start(
                        run_id=run_id,
                        agent_name=agent_name,
                        correlation_id=correlation_id,
                        trigger_source="web_ui",
                        trigger_message=message[:500] if message else "",
                        org_id=org_id,
                        team_node_id=team_node_id,
                    )
                )

                try:
                    # Send agent_started event
                    await response_stream.write(
                        sse_event(
                            "agent_started",
                            {
                                "agent": agent_name,
                                "correlation_id": correlation_id,
                                "run_id": run_id,
                                "timestamp": datetime.utcnow().isoformat(),
                            },
                        )
                    )

                    # Set execution context if available
                    if auth_identity and team_config:
                        from .core.execution_context import set_execution_context

                        set_execution_context(
                            org_id=auth_identity.org_id,
                            team_node_id=auth_identity.team_node_id,
                            team_config=(
                                team_config.model_dump()
                                if hasattr(team_config, "model_dump")
                                else team_config
                            ),
                        )

                    # Use OpenAI Agents SDK streaming
                    sdk_runner = Runner()
                    base_agent = runner.agent

                    # Parse message for multimodal content (embedded images)
                    # Converts <image src="data:..."/> to OpenAI's format
                    parsed_message = parse_multimodal_message(message)
                    message_preview = get_message_preview(
                        parsed_message, max_length=100
                    )

                    logger.info(
                        "starting_streamed_agent_execution",
                        agent_name=agent_name,
                        message_preview=message_preview,
                        max_turns=max_turns,
                        correlation_id=correlation_id,
                        stream_id=stream_id,
                        has_previous_response_id=current_response_id is not None,
                        is_multimodal=isinstance(parsed_message, list),
                    )

                    # Run with streaming - pass previous_response_id for chaining
                    if current_response_id:
                        result = sdk_runner.run_streamed(
                            base_agent,
                            parsed_message,
                            max_turns=max_turns,
                            previous_response_id=current_response_id,
                        )
                    else:
                        result = sdk_runner.run_streamed(
                            base_agent,
                            parsed_message,
                            max_turns=max_turns,
                        )

                    # Helper to drain sub-agent events
                    async def drain_subagent_events():
                        """Drain any pending sub-agent events to the SSE stream."""
                        while not subagent_queue.empty():
                            try:
                                event = subagent_queue.get_nowait()
                                # Format sub-agent event for SSE
                                event_data = {
                                    "agent": event.agent_name,
                                    "parent_agent": event.parent_agent,
                                    "depth": event.depth,
                                    "timestamp": event.timestamp,
                                    **event.data,
                                }
                                await response_stream.write(
                                    sse_event(event.event_type, event_data)
                                )
                            except Exception:
                                break

                    # Stream events as they arrive
                    async for event in result.stream_events():
                        # Drain any sub-agent events that have accumulated
                        await drain_subagent_events()
                        event_type = getattr(event, "type", "unknown")

                        # Handle different event types
                        if event_type == "run_item_stream_event":
                            item = getattr(event, "item", None)
                            if item:
                                item_type = getattr(item, "type", "unknown")

                                # Tool call started
                                if item_type == "tool_call_item":
                                    raw_item = getattr(item, "raw_item", None)
                                    tool_name = getattr(
                                        raw_item, "name", None
                                    ) or getattr(item, "name", "unknown")
                                    tool_args = None
                                    if raw_item and hasattr(raw_item, "arguments"):
                                        try:
                                            tool_args = json.loads(raw_item.arguments)
                                        except Exception:
                                            tool_args = {
                                                "raw": str(raw_item.arguments)[:200]
                                            }

                                    tool_calls_count += 1
                                    await response_stream.write(
                                        sse_event(
                                            "tool_started",
                                            {
                                                "tool": tool_name,
                                                "input": tool_args,
                                                "sequence": tool_calls_count,
                                                "timestamp": datetime.utcnow().isoformat(),
                                            },
                                        )
                                    )

                                # Tool output received
                                elif item_type == "tool_call_output_item":
                                    output = getattr(item, "output", None)
                                    await response_stream.write(
                                        sse_event(
                                            "tool_completed",
                                            {
                                                "output_preview": (
                                                    str(output)[:500]
                                                    if output
                                                    else None
                                                ),
                                                "sequence": tool_calls_count,
                                                "timestamp": datetime.utcnow().isoformat(),
                                            },
                                        )
                                    )

                                # Message output
                                elif item_type == "message_output_item":
                                    content = getattr(item, "content", None)
                                    if content:
                                        await response_stream.write(
                                            sse_event(
                                                "message",
                                                {
                                                    "content_preview": str(content)[
                                                        :500
                                                    ],
                                                    "timestamp": datetime.utcnow().isoformat(),
                                                },
                                            )
                                        )

                        elif event_type == "agent_updated_stream_event":
                            new_agent = getattr(event, "new_agent", None)
                            if new_agent:
                                await response_stream.write(
                                    sse_event(
                                        "agent_handoff",
                                        {
                                            "new_agent": getattr(
                                                new_agent, "name", "unknown"
                                            ),
                                            "timestamp": datetime.utcnow().isoformat(),
                                        },
                                    )
                                )

                    # Drain any remaining sub-agent events
                    await drain_subagent_events()

                    # Get final output
                    duration = time.time() - start_time
                    final_output = getattr(result, "final_output", None) or getattr(
                        result, "output", None
                    )

                    # Convert output to JSON-serializable format
                    def _jsonable(v):
                        if v is None or isinstance(v, (str, int, float, bool)):
                            return v
                        if isinstance(v, (list, tuple)):
                            return [_jsonable(x) for x in v]
                        if isinstance(v, dict):
                            return {str(k): _jsonable(val) for k, val in v.items()}
                        if dataclasses.is_dataclass(v):
                            return _jsonable(dataclasses.asdict(v))
                        model_dump = getattr(v, "model_dump", None)
                        if callable(model_dump):
                            return _jsonable(model_dump())
                        return str(v)

                    # Get last_response_id from result for chaining follow-up queries
                    last_response_id = getattr(result, "last_response_id", None)

                    # Send final result with last_response_id for follow-up queries
                    await response_stream.write(
                        sse_event(
                            "agent_completed",
                            {
                                "success": True,
                                "output": _jsonable(final_output),
                                "duration_seconds": round(duration, 2),
                                "tool_calls_count": tool_calls_count,
                                "correlation_id": correlation_id,
                                "last_response_id": last_response_id,  # For chaining follow-up queries
                                "timestamp": datetime.utcnow().isoformat(),
                            },
                        )
                    )

                    logger.info(
                        "streamed_agent_execution_completed",
                        agent_name=agent_name,
                        duration_seconds=round(duration, 2),
                        tool_calls_count=tool_calls_count,
                        correlation_id=correlation_id,
                    )

                    # Record agent run completion
                    output_summary = ""
                    if isinstance(final_output, dict) and "summary" in final_output:
                        output_summary = str(final_output["summary"])[:1000]
                    elif isinstance(final_output, str):
                        output_summary = final_output[:1000]
                    asyncio.create_task(
                        _record_agent_run_complete(
                            run_id=run_id,
                            status="completed",
                            duration_seconds=duration,
                            output_summary=output_summary,
                            tool_calls_count=tool_calls_count,
                        )
                    )

                except TimeoutError:
                    duration = time.time() - start_time
                    await response_stream.write(
                        sse_event(
                            "agent_completed",
                            {
                                "success": False,
                                "error": f"Agent timed out after {timeout}s",
                                "duration_seconds": round(duration, 2),
                                "correlation_id": correlation_id,
                                "last_response_id": current_response_id,  # For retry
                                "timestamp": datetime.utcnow().isoformat(),
                            },
                        )
                    )
                    # Record timeout
                    asyncio.create_task(
                        _record_agent_run_complete(
                            run_id=run_id,
                            status="timeout",
                            duration_seconds=duration,
                            error_message=f"Agent timed out after {timeout}s",
                            tool_calls_count=tool_calls_count,
                        )
                    )

                except Exception as e:
                    duration = time.time() - start_time
                    logger.error(
                        "streamed_agent_execution_failed",
                        agent_name=agent_name,
                        error=str(e),
                        correlation_id=correlation_id,
                        exc_info=True,
                    )
                    await response_stream.write(
                        sse_event(
                            "agent_completed",
                            {
                                "success": False,
                                "error": str(e),
                                "duration_seconds": round(duration, 2),
                                "correlation_id": correlation_id,
                                "last_response_id": current_response_id,  # For retry
                                "timestamp": datetime.utcnow().isoformat(),
                            },
                        )
                    )
                    # Record failure
                    asyncio.create_task(
                        _record_agent_run_complete(
                            run_id=run_id,
                            status="failed",
                            duration_seconds=duration,
                            error_message=str(e)[:500],
                            tool_calls_count=tool_calls_count,
                        )
                    )

                finally:
                    # Clean up stream registry
                    EventStreamRegistry.close_stream(stream_id)
                    set_current_stream_id(None)

                    # Clear execution context
                    if auth_identity and team_config:
                        from .core.execution_context import clear_execution_context

                        clear_execution_context()

            # Return SSE response
            return ResponseStream(
                stream_events,
                content_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # Disable nginx buffering
                },
            )

        except Exception as e:
            logger.error(
                "stream_endpoint_error",
                agent_name=agent_name,
                error=str(e),
                correlation_id=request.ctx.correlation_id,
                exc_info=True,
            )
            return response.json(
                {
                    "error": str(e),
                    "agent": agent_name,
                    "correlation_id": request.ctx.correlation_id,
                },
                status=500,
            )

    # Get agent info
    @app.get("/agents/<agent_name>")
    async def get_agent_info(request: Request, agent_name: str) -> JSONResponse:
        """Get information about a specific agent."""
        registry = get_agent_registry()
        agent = registry.get_agent(agent_name)

        if not agent:
            return response.json(
                {"error": f"Agent '{agent_name}' not found"},
                status=404,
            )

        return response.json(
            {
                "name": agent.name,
                "model": agent.model if hasattr(agent, "model") else None,
                "tools_count": len(agent.tools) if hasattr(agent, "tools") else 0,
            }
        )

    # Config info
    @app.get("/config")
    async def get_config_info(request: Request) -> JSONResponse:
        """Get current configuration info (redacted)."""
        config = get_config()

        config_info = {
            "environment": config.environment,
            "openai_model": config.openai.model,
            "config_service_enabled": config.use_config_service,
            "k8s_enabled": config.kubernetes.enabled,
            "metrics_enabled": config.metrics.enabled,
        }

        if config.team_config:
            config_info["team_config"] = {
                "mcp_servers": config.team_config.mcp_servers,
                "agents_configured": len(config.team_config.agents),
                "feature_flags": list(config.team_config.feature_flags.keys()),
            }

        return response.json(config_info)

    @app.post("/api/v1/config/reload")
    async def reload_config_endpoint(request: Request) -> JSONResponse:
        """
        Hot-reload configuration from .env file without container restart.

        This is useful after updating integration settings (K8S_ENABLED, etc.)
        to apply changes without recreating the container.
        """
        from .core.config import reload_config

        try:
            new_config = reload_config()

            logger.info(
                "config_reloaded",
                k8s_enabled=new_config.kubernetes.enabled,
                environment=new_config.environment,
            )

            return response.json(
                {
                    "success": True,
                    "message": "Configuration reloaded",
                    "config": {
                        "environment": new_config.environment,
                        "k8s_enabled": new_config.kubernetes.enabled,
                        "openai_model": new_config.openai.model,
                    },
                }
            )

        except Exception as e:
            logger.error("config_reload_failed", error=str(e))
            return response.json(
                {"success": False, "error": str(e)},
                status=500,
            )

    # Tools catalog
    @app.get("/api/v1/tools/catalog")
    async def get_tools_catalog(request: Request) -> JSONResponse:
        """
        Get the complete tools catalog available to the team.

        Includes:
        - Built-in tools
        - Custom MCP tools (from team config)

        Returns a list of tool definitions with name, description, and category.
        """
        try:
            from .tools.tool_pool import get_team_tool_pool_with_sources

            config = get_config()
            team_config = config.team_config if hasattr(config, "team_config") else None

            # Fetch team-specific config from config service if available
            if config.use_config_service:
                team_token = request.headers.get(
                    "X-IncidentFox-Team-Token"
                ) or request.headers.get("Authorization", "").replace("Bearer ", "")
                if team_token:
                    try:
                        from .core.config_service import get_config_service_client

                        client = get_config_service_client()
                        team_config = client.fetch_effective_config(
                            team_token=team_token
                        )
                        logger.debug(
                            "team_config_fetched_for_catalog",
                            team_token=team_token[:10] + "...",
                        )
                    except Exception as e:
                        logger.warning(
                            "failed_to_fetch_team_config_for_catalog", error=str(e)
                        )

            # Get the tool pool with source information
            tool_pool, tool_sources = get_team_tool_pool_with_sources(team_config)

            # Convert tools to catalog format
            tools_list = []
            for tool_name, tool_func in tool_pool.items():
                tool_def = {
                    "id": tool_name,
                    "name": tool_name.replace("_", " ").title(),
                    "description": (
                        getattr(tool_func, "__doc__", "").split("\n")[0]
                        if getattr(tool_func, "__doc__", None)
                        else ""
                    ),
                    "category": _infer_tool_category(tool_name),
                    "source": tool_sources.get(tool_name, "built-in"),  # Include source
                }
                tools_list.append(tool_def)

            logger.info("tools_catalog_fetched", count=len(tools_list))

            return response.json(
                {
                    "tools": tools_list,
                    "count": len(tools_list),
                }
            )

        except Exception as e:
            logger.error("failed_to_get_tools_catalog", error=str(e))
            return response.json(
                {"error": f"Failed to get tools catalog: {str(e)}"},
                status=500,
            )

    # MCP Health Check
    @app.get("/api/v1/mcp/health")
    async def check_mcp_health(request: Request) -> JSONResponse:
        """
        Check health status of MCP servers for a team.

        This performs lightweight connection checks (spawn + initialize + disconnect)
        for each MCP server configured for the team. Does NOT execute any tools.

        Response time: ~500ms per MCP server

        Returns:
            {
                "servers": {
                    "mcp_id": {
                        "status": "healthy|unhealthy|timeout|error",
                        "checked_at": "2026-01-10T21:00:00Z",
                        "error": "error message if any"
                    }
                },
                "checked_at": "2026-01-10T21:00:00Z"
            }
        """
        try:
            import asyncio
            from datetime import datetime

            from .integrations.mcp.generic_server import GenericMCPServer

            config = get_config()
            team_config = config.team_config if hasattr(config, "team_config") else None

            # Fetch team-specific config from config service if available
            if config.use_config_service:
                team_token = request.headers.get(
                    "X-IncidentFox-Team-Token"
                ) or request.headers.get("Authorization", "").replace("Bearer ", "")
                if team_token:
                    try:
                        from .core.config_service import get_config_service_client

                        client = get_config_service_client()
                        team_config = client.fetch_effective_config(
                            team_token=team_token
                        )
                        logger.debug(
                            "team_config_fetched_for_health",
                            team_token=team_token[:10] + "...",
                        )
                    except Exception as e:
                        logger.warning(
                            "failed_to_fetch_team_config_for_health", error=str(e)
                        )

            if not team_config:
                return response.json(
                    {
                        "servers": {},
                        "checked_at": datetime.utcnow().isoformat() + "Z",
                    }
                )

            # Get MCP configurations
            mcps_config = (
                getattr(team_config, "mcps", {})
                if hasattr(team_config, "mcps")
                else team_config.get("mcps", {})
            )

            if not mcps_config:
                return response.json(
                    {
                        "servers": {},
                        "checked_at": datetime.utcnow().isoformat() + "Z",
                    }
                )

            # Collect all enabled MCPs
            disabled_mcps = set(mcps_config.get("disabled", []))
            team_mcps = []

            # Default MCPs from org
            for mcp in mcps_config.get("default", []):
                if mcp.get("id") not in disabled_mcps and mcp.get("enabled", True):
                    team_mcps.append(mcp)

            # Team-added MCPs
            for mcp in mcps_config.get("team_added", []):
                if mcp.get("id") not in disabled_mcps and mcp.get("enabled", True):
                    team_mcps.append(mcp)

            async def check_single_mcp(mcp_config: dict) -> tuple:
                """Check health of a single MCP server."""
                mcp_id = mcp_config.get("id", "unknown")

                try:
                    server = GenericMCPServer(
                        name=mcp_id,
                        command=mcp_config.get("command", ""),
                        args=mcp_config.get("args", []),
                        env=mcp_config.get("env", {}),
                    )

                    # Try to connect with timeout
                    connected = await asyncio.wait_for(server.connect(), timeout=2.0)

                    # Disconnect immediately
                    await server.disconnect()

                    if connected:
                        return (
                            mcp_id,
                            {
                                "status": "healthy",
                                "checked_at": datetime.utcnow().isoformat() + "Z",
                            },
                        )
                    else:
                        return (
                            mcp_id,
                            {
                                "status": "unhealthy",
                                "checked_at": datetime.utcnow().isoformat() + "Z",
                                "error": "Connection failed",
                            },
                        )

                except TimeoutError:
                    return (
                        mcp_id,
                        {
                            "status": "timeout",
                            "checked_at": datetime.utcnow().isoformat() + "Z",
                            "error": "Connection timeout (2s)",
                        },
                    )
                except Exception as e:
                    return (
                        mcp_id,
                        {
                            "status": "error",
                            "checked_at": datetime.utcnow().isoformat() + "Z",
                            "error": str(e),
                        },
                    )

            # Check all MCPs in parallel
            health_checks = [check_single_mcp(mcp) for mcp in team_mcps]
            results = await asyncio.gather(*health_checks)

            # Build results dict
            servers_health = dict(results)

            logger.info(
                "mcp_health_checked",
                total_servers=len(team_mcps),
                healthy=sum(
                    1 for r in servers_health.values() if r["status"] == "healthy"
                ),
            )

            return response.json(
                {
                    "servers": servers_health,
                    "checked_at": datetime.utcnow().isoformat() + "Z",
                }
            )

        except Exception as e:
            logger.error("failed_to_check_mcp_health", error=str(e))
            return response.json(
                {"error": f"Failed to check MCP health: {str(e)}"},
                status=500,
            )

    # NOTE: Webhook endpoints have been removed. All webhooks now handled by Orchestrator.
    # See: orchestrator/src/incidentfox_orchestrator/webhooks/router.py

    # =========================================================================
    # Graceful Shutdown Handler
    # =========================================================================
    # When the server is stopping (SIGTERM, deployment rollout, scale-down),
    # mark all in-flight agent runs as failed to prevent orphaned "running" status.

    @app.before_server_stop
    async def cleanup_in_flight_runs(app, loop):
        """
        Mark all in-flight agent runs as failed when server is shutting down.

        This prevents runs from being stuck in 'running' status when:
        - Pod is terminated (deployment rollout, scale-down)
        - Process receives SIGTERM/SIGINT
        - Container is stopped
        """
        mark_shutdown_in_progress()  # Prevent new runs from being registered

        in_flight = get_in_flight_runs()
        if not in_flight:
            logger.info("graceful_shutdown_no_in_flight_runs")
            return

        logger.info(
            "graceful_shutdown_marking_in_flight_runs",
            count=len(in_flight),
            run_ids=in_flight,
        )

        # Mark each in-flight run as failed
        for run_id in in_flight:
            try:
                # Use short timeout - we're shutting down, can't wait long
                await asyncio.wait_for(
                    _record_agent_run_complete(
                        run_id=run_id,
                        status="failed",
                        duration_seconds=0,  # Unknown duration
                        error_message="Agent process shutdown while run was in progress",
                    ),
                    timeout=2.0,  # Short timeout during shutdown
                )
                logger.info(
                    "graceful_shutdown_run_marked_failed",
                    run_id=run_id,
                )
            except TimeoutError:
                logger.warning(
                    "graceful_shutdown_run_mark_timeout",
                    run_id=run_id,
                    message="Cleanup job will catch this",
                )
            except Exception as e:
                logger.warning(
                    "graceful_shutdown_run_mark_error",
                    run_id=run_id,
                    error=str(e),
                )

        logger.info(
            "graceful_shutdown_complete",
            processed_count=len(in_flight),
        )

    @app.exception(Exception)
    async def handle_exception(request: Request, exception: Exception):
        logger.error(
            "unhandled_exception",
            error=str(exception),
            path=request.path,
            exc_info=True,
        )

        return response.json(
            {
                "error": "Internal server error",
                "message": str(exception),
                "correlation_id": getattr(request.ctx, "correlation_id", None),
            },
            status=500,
        )

    return app


def start_api_server(host: str = "0.0.0.0", port: int = 8080):
    """Start the API server."""
    app = create_app()

    logger.info("starting_api_server", host=host, port=port)

    # Sanic runs synchronously - it manages its own event loop
    app.run(
        host=host,
        port=port,
        access_log=True,
        auto_reload=False,
        single_process=True,
    )


if __name__ == "__main__":
    start_api_server()
