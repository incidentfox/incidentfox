"""
Sandbox Server - FastAPI runtime running inside sandbox container on port 8888.

This server exposes endpoints for executing and interrupting investigations.
It maintains persistent agent sessions per thread_id to enable interrupts.

Streams structured events via SSE (Server-Sent Events) for client consumption.

Key features:
- **Config-driven agents**: Loads team config from Config Service via TEAM_TOKEN
- **Multi-LLM support**: Claude, Gemini, OpenAI via LiteLLM
- **Dynamic agent hierarchy**: Builds agents from config with topological sorting

Endpoints:
- GET /health - Health check
- GET /config - View loaded configuration (debug)
- POST /execute - Execute investigation (streaming SSE)
- POST /interrupt - Interrupt current execution
- POST /answer - Provide answer to AskUserQuestion
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.agent import Agent
from ..core.agent_builder import build_agent_hierarchy, normalize_model_name
from ..core.config import Config, get_config, reload_config
from ..core.events import (
    StreamEvent,
    error_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)
from ..core.runner import Runner, RunResult
from .manager import SandboxExecutionError, SandboxManager

logger = logging.getLogger(__name__)

app = FastAPI(
    title="IncidentFox Unified Agent Sandbox",
    description="Config-driven investigation agents with multi-LLM support",
    version="2.0.0",
)


# =============================================================================
# Session Management
# =============================================================================


@dataclass
class AgentSession:
    """
    Manages a persistent agent session for a thread.

    Sessions maintain:
    - Built agent hierarchy from team config
    - Conversation history for context
    - Interrupt flag for cancellation
    """

    thread_id: str
    agents: Dict[str, Agent] = field(default_factory=dict)
    root_agent: Optional[Agent] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    is_running: bool = False
    _interrupt_flag: bool = False
    model: str = ""

    def interrupt(self):
        """Signal the session to stop."""
        self._interrupt_flag = True
        self.is_running = False

    def reset_interrupt(self):
        """Reset interrupt flag for new execution."""
        self._interrupt_flag = False

    @property
    def was_interrupted(self) -> bool:
        return self._interrupt_flag


# Global session manager: thread_id -> AgentSession
_sessions: Dict[str, AgentSession] = {}
_session_lock = asyncio.Lock()

# Cached config and agents (rebuilt on config reload)
_cached_config: Optional[Config] = None
_cached_agents: Optional[Dict[str, Agent]] = None

# Sandbox manager (lazy initialized, used when USE_GVISOR=true)
_sandbox_manager: Optional[SandboxManager] = None


def _is_sandbox_mode() -> bool:
    """Check if running in sandbox manager mode (creates gVisor pods)."""
    return os.getenv("USE_GVISOR", "false").lower() == "true"


def _get_sandbox_manager() -> SandboxManager:
    """Get or create the sandbox manager."""
    global _sandbox_manager
    if _sandbox_manager is None:
        namespace = os.getenv("SANDBOX_NAMESPACE") or os.getenv("NAMESPACE", "default")
        image = os.getenv("SANDBOX_IMAGE") or os.getenv("UNIFIED_AGENT_IMAGE")
        _sandbox_manager = SandboxManager(namespace=namespace, image=image)
    return _sandbox_manager


async def _async_stream_response(response):
    """Convert sync streaming response to async generator.

    Reads chunks from a synchronous requests.Response in a thread pool
    to avoid blocking the async event loop.
    """

    def _get_next(it):
        try:
            return next(it)
        except StopIteration:
            return None

    it = response.iter_content(chunk_size=None)
    while True:
        chunk = await asyncio.to_thread(_get_next, it)
        if chunk is None:
            break
        yield chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk


def _get_effective_config() -> Dict[str, Any]:
    """
    Get effective config for agent building.

    Converts TeamConfig to the dict format expected by build_agent_hierarchy.
    """
    config = get_config()

    if config.team_config is None:
        # Return minimal default config
        return {
            "agents": {
                "investigator": {
                    "enabled": True,
                    "name": "Investigator",
                    "model": {"name": config.llm_model},
                    "tools": {"enabled": ["*"]},
                }
            }
        }

    # Convert TeamConfig to dict format
    team_config = config.team_config
    agents_dict = {}

    for agent_name, agent_config in team_config.agents_config.items():
        agents_dict[agent_name] = {
            "enabled": agent_config.enabled,
            "name": agent_config.name or agent_name,
            "model": {
                "name": agent_config.model.name,
                "temperature": agent_config.model.temperature,
                "max_tokens": agent_config.model.max_tokens,
                "reasoning": agent_config.model.reasoning,
                "verbosity": agent_config.model.verbosity,
            },
            "prompt": {
                "system": agent_config.prompt.system,
                "prefix": agent_config.prompt.prefix,
                "suffix": agent_config.prompt.suffix,
            },
            "tools": {
                "enabled": agent_config.tools.enabled,
                "disabled": agent_config.tools.disabled,
            },
            "sub_agents": agent_config.sub_agents,
            "max_turns": agent_config.max_turns,
        }

    # If no agents defined, create default investigator
    if not agents_dict:
        agents_dict["investigator"] = {
            "enabled": True,
            "name": "Investigator",
            "model": {"name": config.llm_model},
            "tools": {"enabled": ["*"]},
        }

    return {
        "agents": agents_dict,
        "integrations": team_config.integrations,
        "mcp_servers": team_config.mcp_servers,
    }


def _build_agents_from_config() -> Dict[str, Agent]:
    """
    Build agent hierarchy from team configuration.

    This is called once on startup and cached.
    Agents are rebuilt if config is reloaded.
    """
    global _cached_config, _cached_agents

    config = get_config()

    # Check if we need to rebuild
    if _cached_agents is not None and _cached_config is config:
        return _cached_agents

    effective_config = _get_effective_config()

    logger.info(
        f"Building agents from config: {list(effective_config.get('agents', {}).keys())}"
    )

    try:
        agents = build_agent_hierarchy(effective_config, team_config=config.team_config)
        _cached_config = config
        _cached_agents = agents

        logger.info(f"Built {len(agents)} agents: {list(agents.keys())}")
        for name, agent in agents.items():
            logger.info(
                f"  - {name}: model={agent.model}, tools={len(agent.tools or [])}"
            )

        return agents
    except Exception as e:
        logger.error(f"Failed to build agents from config: {e}")
        # Return minimal default agent on error
        from ..core.agent import Agent

        default_agent = Agent(
            name="Investigator",
            instructions="You are an expert SRE investigator. Help debug production issues.",
            model=config.llm_model,
        )
        return {"investigator": default_agent}


async def get_or_create_session(thread_id: str) -> AgentSession:
    """
    Get existing session or create new one for thread_id.

    Sessions use agents built from team configuration loaded via TEAM_TOKEN.
    """
    async with _session_lock:
        if thread_id not in _sessions:
            # Build agents from config
            agents = _build_agents_from_config()

            # Get root agent (prefer 'investigator' or 'planner', fallback to first)
            root_agent = (
                agents.get("investigator")
                or agents.get("planner")
                or next(iter(agents.values()), None)
            )

            if root_agent is None:
                raise RuntimeError("No agents available - check configuration")

            config = get_config()

            session = AgentSession(
                thread_id=thread_id,
                agents=agents,
                root_agent=root_agent,
                model=config.llm_model,
            )

            _sessions[thread_id] = session
            logger.info(
                f"Created session {thread_id} with root agent: {root_agent.name}"
            )

        return _sessions[thread_id]


# =============================================================================
# Request/Response Models
# =============================================================================


class ImageData(BaseModel):
    """Image data for multimodal input."""

    type: str = "base64"
    media_type: str
    data: str
    filename: Optional[str] = None


class ExecuteRequest(BaseModel):
    """Request to execute an investigation."""

    prompt: str
    thread_id: Optional[str] = None
    images: Optional[List[ImageData]] = None
    agent: Optional[str] = None  # Specific agent to use (default: root)
    max_turns: Optional[int] = None


class InvestigateRequest(BaseModel):
    """
    Request to investigate - compatibility endpoint for slack-bot.

    This model accepts the legacy /investigate request format used by slack-bot,
    which includes team_token in the request body instead of environment.
    """

    prompt: str
    thread_id: Optional[str] = None
    tenant_id: Optional[str] = None  # Slack team_id for credential lookup
    team_id: Optional[str] = None  # Slack team_id
    team_token: Optional[str] = None  # Team token for config loading
    images: Optional[List[ImageData]] = None
    file_attachments: Optional[List[Dict[str, Any]]] = (
        None  # File metadata (not used yet)
    )


class InterruptRequest(BaseModel):
    """Request to interrupt the investigation."""

    thread_id: str


class AnswerRequest(BaseModel):
    """Request to provide answer to AskUserQuestion."""

    thread_id: str
    answers: dict


# =============================================================================
# Endpoints
# =============================================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    config = get_config()
    return {
        "status": "healthy",
        "service": "unified-agent-sandbox",
        "version": "2.0.0",
        "mode": "sandbox-manager" if _is_sandbox_mode() else "direct",
        "active_sessions": len(_sessions),
        "model": config.llm_model,
        "tenant_id": config.tenant_id,
        "team_id": config.team_id,
        "config_loaded": config.team_config is not None,
    }


@app.get("/config")
async def get_loaded_config():
    """
    View the loaded configuration (for debugging).

    Shows which agents are configured and their settings.
    """
    config = get_config()
    effective = _get_effective_config()

    return {
        "tenant_id": config.tenant_id,
        "team_id": config.team_id,
        "llm_model": config.llm_model,
        "config_source": "config_service" if os.getenv("TEAM_TOKEN") else "local",
        "agents": {
            name: {
                "enabled": cfg.get("enabled", True),
                "model": cfg.get("model", {}).get("name", "default"),
                "tools_enabled": cfg.get("tools", {}).get("enabled", []),
                "sub_agents": list(cfg.get("sub_agents", {}).keys()),
            }
            for name, cfg in effective.get("agents", {}).items()
        },
        "integrations": list(effective.get("integrations", {}).keys()),
    }


@app.post("/config/reload")
async def reload_configuration():
    """
    Force reload of configuration from Config Service.

    Useful after config changes to pick up new agent settings.
    """
    global _cached_config, _cached_agents

    # Clear cache
    _cached_config = None
    _cached_agents = None

    # Reload config
    reload_config()

    # Rebuild agents
    agents = _build_agents_from_config()

    return {
        "status": "reloaded",
        "agents": list(agents.keys()),
    }


@app.get("/sessions")
async def list_sessions():
    """List active sessions (for debugging)."""
    return {
        "sessions": [
            {
                "thread_id": thread_id,
                "is_running": session.is_running,
                "root_agent": session.root_agent.name if session.root_agent else None,
                "model": session.model,
                "history_length": len(session.conversation_history),
            }
            for thread_id, session in _sessions.items()
        ]
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """
    Execute an investigation agent with the given prompt (streaming SSE).

    The agent is built from team configuration loaded via TEAM_TOKEN.
    Supports multi-LLM (Claude, Gemini, OpenAI) based on config.
    """
    thread_id = request.thread_id or os.getenv("THREAD_ID", "default")
    max_turns = request.max_turns or int(os.getenv("AGENT_MAX_TURNS", "25"))

    # Get or create session
    try:
        session = await get_or_create_session(thread_id)
    except Exception as e:
        logger.error(f"Failed to create session: {e}")

        async def error_stream():
            yield error_event(
                thread_id, f"Failed to initialize: {e}", recoverable=False
            ).to_sse()

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Get agent to use (specific or root)
    agent = session.root_agent
    if request.agent and request.agent in session.agents:
        agent = session.agents[request.agent]

    # Reset interrupt flag
    session.reset_interrupt()
    session.is_running = True

    async def stream():
        try:
            logger.info(
                f"Starting execution for thread {thread_id} with agent {agent.name}"
            )
            event_count = 0

            # Stream events from Runner
            async for event in Runner.run_streaming(
                agent,
                request.prompt,
                max_turns=max_turns,
                context={"thread_id": thread_id},
            ):
                if session.was_interrupted:
                    yield thought_event(thread_id, "Execution interrupted.").to_sse()
                    yield result_event(
                        thread_id,
                        "Task interrupted. Send a new message to continue.",
                        success=True,
                        subtype="interrupted",
                    ).to_sse()
                    break

                event_count += 1

                # Convert Runner StreamEvent to our StreamEvent format
                if hasattr(event, "to_sse"):
                    yield event.to_sse()
                elif isinstance(event, dict):
                    # Handle dict events from Runner
                    sse_event = _convert_runner_event(thread_id, event)
                    yield sse_event.to_sse()
                else:
                    yield f"data: {json.dumps({'type': 'unknown', 'data': str(event)})}\n\n"

            logger.info(
                f"Execution completed: {event_count} events for thread {thread_id}"
            )

        except Exception as e:
            logger.error(f"Execution error for {thread_id}: {e}", exc_info=True)
            yield error_event(
                thread_id, f"Execution failed: {e}", recoverable=False
            ).to_sse()

        finally:
            session.is_running = False

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/investigate")
async def investigate(request: InvestigateRequest):
    """
    Investigation endpoint - routes to sandbox or direct execution.

    In sandbox mode (USE_GVISOR=true):
      - Creates/reuses gVisor sandbox pod via SandboxManager
      - Routes request through sandbox-router
      - Credentials injected via Envoy sidecar + credential-resolver

    In direct mode:
      - Executes agent locally (no isolation)
    """
    if _is_sandbox_mode():
        return await _investigate_via_sandbox(request)
    return await _investigate_direct(request)


async def _investigate_direct(request: InvestigateRequest):
    """Execute investigation directly in this process (no sandbox)."""
    # Set team_token as env var if provided (for config service auth)
    if request.team_token:
        os.environ["TEAM_TOKEN"] = request.team_token
        logger.info(f"Set TEAM_TOKEN from request for thread {request.thread_id}")

        # Reload config to pick up new team token
        global _cached_config, _cached_agents
        _cached_config = None
        _cached_agents = None

    # Forward to execute with compatible fields
    execute_request = ExecuteRequest(
        prompt=request.prompt,
        thread_id=request.thread_id,
        images=request.images,
    )
    return await execute(execute_request)


async def _investigate_via_sandbox(request: InvestigateRequest):
    """Execute investigation in an isolated gVisor sandbox pod."""
    thread_id = request.thread_id or f"inv-{int(time.time())}"
    tenant_id = request.tenant_id or os.getenv("INCIDENTFOX_TENANT_ID", "default")
    team_id = request.team_id or os.getenv("INCIDENTFOX_TEAM_ID", "default")

    manager = _get_sandbox_manager()

    async def stream():
        try:
            # Check for existing sandbox for this thread
            sandbox_info = await asyncio.to_thread(manager.get_sandbox, thread_id)

            if sandbox_info is None:
                yield thought_event(thread_id, "Creating isolated sandbox...").to_sse()

                sandbox_info = await asyncio.to_thread(
                    manager.create_sandbox,
                    thread_id=thread_id,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    team_token=request.team_token,
                )

                yield thought_event(
                    thread_id, "Waiting for sandbox to be ready..."
                ).to_sse()

                ready = await asyncio.to_thread(manager.wait_for_ready, thread_id, 120)
                if not ready:
                    yield error_event(
                        thread_id,
                        "Sandbox failed to start within timeout",
                        recoverable=False,
                    ).to_sse()
                    return

                yield thought_event(
                    thread_id, "Sandbox ready. Starting investigation..."
                ).to_sse()

            # Execute in sandbox via router (streaming SSE)
            images = (
                [img.model_dump() for img in request.images] if request.images else None
            )
            response = await asyncio.to_thread(
                manager.execute_in_sandbox, sandbox_info, request.prompt, images
            )

            # Forward SSE stream from sandbox pod
            async for chunk in _async_stream_response(response):
                yield chunk

        except SandboxExecutionError as e:
            logger.error(f"Sandbox execution failed: {e}", exc_info=True)
            yield error_event(thread_id, str(e), recoverable=False).to_sse()
        except Exception as e:
            logger.error(f"Sandbox error: {e}", exc_info=True)
            yield error_event(
                thread_id, f"Sandbox error: {e}", recoverable=False
            ).to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _convert_runner_event(thread_id: str, event: dict) -> StreamEvent:
    """Convert Runner event dict to StreamEvent."""
    event_type = event.get("type", "unknown")
    data = event.get("data", {})

    if event_type == "thought":
        return thought_event(thread_id, data.get("text", ""))
    elif event_type == "tool_start":
        return tool_start_event(thread_id, data.get("tool", ""), data.get("args", {}))
    elif event_type == "tool_end":
        return tool_end_event(
            thread_id,
            data.get("tool", ""),
            success=data.get("success", True),
            output=data.get("output", ""),
        )
    elif event_type == "result":
        return result_event(thread_id, data.get("text", ""), success=True)
    elif event_type == "error":
        return error_event(
            thread_id, data.get("message", "Unknown error"), recoverable=False
        )
    else:
        return thought_event(thread_id, str(data))


@app.post("/interrupt")
async def interrupt(request: InterruptRequest):
    """
    Interrupt the current execution and stop.

    After interrupt, new messages can be sent via execute endpoint.
    """
    if _is_sandbox_mode():
        return await _interrupt_via_sandbox(request)
    return await _interrupt_direct(request)


async def _interrupt_direct(request: InterruptRequest):
    """Interrupt a local execution."""
    thread_id = request.thread_id

    async def stream():
        try:
            async with _session_lock:
                if thread_id not in _sessions:
                    yield error_event(
                        thread_id, "No active session found", recoverable=False
                    ).to_sse()
                    return
                session = _sessions[thread_id]

            # Signal interrupt
            session.interrupt()

            yield thought_event(thread_id, "Interrupting current task...").to_sse()
            yield result_event(
                thread_id,
                "Task interrupted. Send a new message to continue.",
                success=True,
                subtype="interrupted",
            ).to_sse()

        except Exception as e:
            yield error_event(
                thread_id, f"Interrupt failed: {e}", recoverable=False
            ).to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _interrupt_via_sandbox(request: InterruptRequest):
    """Interrupt an execution running in a sandbox pod."""
    thread_id = request.thread_id
    manager = _get_sandbox_manager()

    async def stream():
        try:
            sandbox_info = await asyncio.to_thread(manager.get_sandbox, thread_id)
            if sandbox_info is None:
                yield error_event(
                    thread_id, "No active sandbox found", recoverable=False
                ).to_sse()
                return

            response = await asyncio.to_thread(manager.interrupt_sandbox, sandbox_info)

            # Forward SSE stream from sandbox
            async for chunk in _async_stream_response(response):
                yield chunk

        except Exception as e:
            logger.error(f"Sandbox interrupt failed: {e}", exc_info=True)
            yield error_event(
                thread_id, f"Interrupt failed: {e}", recoverable=False
            ).to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/answer")
async def answer_question(request: AnswerRequest):
    """Receive answer to AskUserQuestion from main server."""
    thread_id = request.thread_id

    async with _session_lock:
        if thread_id not in _sessions:
            raise HTTPException(404, f"No active session for {thread_id}")
        # Note: Answer handling requires additional state management
        # This is a placeholder for future implementation

    return {"status": "ok", "thread_id": thread_id, "note": "Answer queued"}


@app.post("/cleanup")
async def cleanup_session(thread_id: str):
    """Manually cleanup a session."""
    async with _session_lock:
        if thread_id in _sessions:
            session = _sessions.pop(thread_id)
            session.interrupt()
            return {"status": "cleaned", "thread_id": thread_id}
        return {"status": "not_found", "thread_id": thread_id}


@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    config = get_config()
    sandbox_mode = _is_sandbox_mode()
    logger.info("Sandbox server starting...")
    logger.info(f"  Mode: {'sandbox-manager' if sandbox_mode else 'direct'}")
    logger.info(f"  Tenant: {config.tenant_id}")
    logger.info(f"  Team: {config.team_id}")
    logger.info(f"  Model: {config.llm_model}")
    logger.info(f"  Config loaded: {config.team_config is not None}")

    if sandbox_mode:
        logger.info(f"  Sandbox image: {os.getenv('SANDBOX_IMAGE', 'not set')}")
        logger.info(f"  Sandbox namespace: {os.getenv('SANDBOX_NAMESPACE', 'not set')}")
        logger.info(f"  gVisor: {os.getenv('USE_GVISOR', 'false')}")
    else:
        # Pre-build agents only in direct mode (sandbox pods build their own)
        try:
            agents = _build_agents_from_config()
            logger.info(f"  Agents available: {list(agents.keys())}")
        except Exception as e:
            logger.warning(f"  Failed to pre-build agents: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up all sessions on shutdown."""
    async with _session_lock:
        for session in _sessions.values():
            session.interrupt()
        _sessions.clear()


def run_server():
    """Run the sandbox server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="info")


if __name__ == "__main__":
    run_server()
