"""
Sandbox Server - FastAPI runtime running inside sandbox container on port 8888.

This server exposes endpoints for executing and interrupting investigations.
It maintains persistent agent sessions per thread_id to enable interrupts.

Streams structured events via SSE (Server-Sent Events) for client consumption.

Key features:
- **Config-driven**: Loads team config from Config Service via TEAM_TOKEN
- **Multi-LLM support**: Claude, Gemini, OpenAI via LiteLLM (OpenHandsProvider)
- **Conversation persistence**: Sessions maintain full conversation history across calls

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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.config import Config, get_config, reload_config
from ..core.events import (
    error_event,
    result_event,
    thought_event,
)
from ..providers.base import LLMProvider, ProviderConfig, create_provider
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
    - OpenHandsProvider with conversation history
    - Interrupt flag for cancellation
    """

    thread_id: str
    provider: Optional[LLMProvider] = None
    is_running: bool = False
    _interrupt_flag: bool = False

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


def _get_allowed_tools(config: Config) -> list[str]:
    """
    Get allowed tools from team config or defaults.

    Maps team config tool settings to the tool names expected by OpenHandsProvider.
    """
    default_tools = [
        "Bash",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
        "Skill",
        "Task",
    ]

    if config.team_config is None:
        return default_tools

    # Get root agent config (prefer 'investigator' or first available)
    agents_config = config.team_config.agents_config
    root_config = agents_config.get("investigator") or next(
        iter(agents_config.values()), None
    )

    if root_config is None:
        return default_tools

    enabled = root_config.tools.enabled
    if "*" in enabled:
        if root_config.tools.disabled:
            return [t for t in default_tools if t not in root_config.tools.disabled]
        return default_tools

    return enabled


async def get_or_create_session(thread_id: str) -> AgentSession:
    """
    Get existing session or create new one for thread_id.

    Creates an OpenHandsProvider-based session that maintains conversation
    history across calls, enabling multi-turn investigations.
    """
    async with _session_lock:
        if thread_id not in _sessions:
            config = get_config()

            provider_config = ProviderConfig(
                cwd=os.getenv("WORKSPACE_DIR", "/workspace"),
                thread_id=thread_id,
                model=config.llm_model,
                allowed_tools=_get_allowed_tools(config),
            )

            provider = create_provider(provider_config)
            await provider.start()

            session = AgentSession(thread_id=thread_id, provider=provider)
            _sessions[thread_id] = session
            logger.info(f"Created session {thread_id} with model: {config.llm_model}")

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

    Shows provider settings and active sessions.
    """
    config = get_config()

    return {
        "tenant_id": config.tenant_id,
        "team_id": config.team_id,
        "llm_model": config.llm_model,
        "config_source": "config_service" if os.getenv("TEAM_TOKEN") else "local",
        "allowed_tools": _get_allowed_tools(config),
        "active_sessions": len(_sessions),
    }


@app.post("/config/reload")
async def reload_configuration():
    """
    Force reload of configuration from Config Service.

    Useful after config changes to pick up new agent settings.
    Clears all sessions so new ones are created with updated config.
    """
    # Close existing sessions
    async with _session_lock:
        for session in _sessions.values():
            if session.provider:
                await session.provider.close()
        _sessions.clear()

    # Reload config
    reload_config()
    config = get_config()

    return {
        "status": "reloaded",
        "model": config.llm_model,
        "tools": _get_allowed_tools(config),
    }


@app.get("/sessions")
async def list_sessions():
    """List active sessions (for debugging)."""
    return {
        "sessions": [
            {
                "thread_id": thread_id,
                "is_running": session.is_running,
                "has_provider": session.provider is not None,
                "history_length": (
                    len(session.provider._conversation_history)
                    if session.provider
                    and hasattr(session.provider, "_conversation_history")
                    else 0
                ),
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

    # Reset interrupt flag
    session.reset_interrupt()
    session.is_running = True

    # Build images list for multimodal input
    images_list = None
    if request.images:
        images_list = [
            {
                "type": img.type,
                "media_type": img.media_type,
                "data": img.data,
            }
            for img in request.images
        ]

    async def stream():
        try:
            logger.info(f"Starting execution for thread {thread_id}")
            event_count = 0

            # Stream events from provider (maintains conversation history)
            async for event in session.provider.execute(
                request.prompt,
                images=images_list,
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

                if hasattr(event, "to_sse"):
                    yield event.to_sse()
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
        reload_config()

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
            if session.provider:
                await session.provider.close()
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
        logger.info("  Provider: OpenHands (LiteLLM)")
        logger.info(f"  Allowed tools: {_get_allowed_tools(config)}")
        logger.info(f"  Workspace: {os.getenv('WORKSPACE_DIR', '/workspace')}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up all sessions on shutdown."""
    async with _session_lock:
        for session in _sessions.values():
            session.interrupt()
            if session.provider:
                await session.provider.close()
        _sessions.clear()


def run_server():
    """Run the sandbox server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="info")


if __name__ == "__main__":
    run_server()
