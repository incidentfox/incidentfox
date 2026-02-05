"""
Sandbox Server - FastAPI runtime running inside sandbox container on port 8888.

This server exposes endpoints for executing and interrupting investigations.
It maintains persistent agent sessions per thread_id to enable interrupts.

Streams structured events via SSE (Server-Sent Events) for client consumption.

Endpoints:
- GET /health - Health check
- POST /execute - Execute investigation (streaming SSE)
- POST /interrupt - Interrupt current execution
- POST /answer - Provide answer to AskUserQuestion
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.events import StreamEvent, error_event
from ..providers import ProviderConfig, SubagentConfig, create_provider

logger = logging.getLogger(__name__)

app = FastAPI(
    title="IncidentFox Unified Agent Sandbox",
    description="Executes investigation agents in isolated sandbox with interrupt support",
    version="1.0.0",
)

# Global session manager: thread_id -> Provider instance
_sessions: Dict[str, any] = {}
_session_lock = asyncio.Lock()


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


class InterruptRequest(BaseModel):
    """Request to interrupt the investigation."""

    thread_id: str


class AnswerRequest(BaseModel):
    """Request to provide answer to AskUserQuestion."""

    thread_id: str
    answers: dict


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "unified-agent-sandbox",
        "active_sessions": len(_sessions),
    }


@app.get("/sessions")
async def list_sessions():
    """List active sessions (for debugging)."""
    return {
        "sessions": [
            {"thread_id": thread_id, "is_running": session.is_running}
            for thread_id, session in _sessions.items()
        ]
    }


async def get_or_create_session(thread_id: str):
    """
    Get existing session or create new one for thread_id.

    Creates an OpenHands provider configured for the sandbox environment.
    """
    async with _session_lock:
        if thread_id not in _sessions:
            # Create provider config from environment
            cwd = os.getenv("WORKSPACE_DIR", "/workspace")
            model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-20250514")

            # Default subagents for investigation
            subagents = {
                "log-analyst": SubagentConfig(
                    name="log-analyst",
                    description="Specialized in log analysis and pattern detection",
                    prompt="You are a log analysis expert. Analyze logs to find errors, patterns, and anomalies.",
                    tools=["Bash", "Read", "Glob", "Grep"],
                    model="sonnet",
                ),
                "k8s-debugger": SubagentConfig(
                    name="k8s-debugger",
                    description="Kubernetes debugging specialist",
                    prompt="You are a Kubernetes expert. Debug pod issues, deployments, and cluster problems.",
                    tools=["Bash", "Read", "Glob", "Grep"],
                    model="sonnet",
                ),
            }

            config = ProviderConfig(
                cwd=cwd,
                thread_id=thread_id,
                model=model,
                allowed_tools=[
                    "Bash",
                    "Read",
                    "Write",
                    "Edit",
                    "Glob",
                    "Grep",
                    "Task",
                    "Skill",
                ],
                subagents=subagents,
            )

            session = create_provider(config)
            await session.start()
            _sessions[thread_id] = session

        return _sessions[thread_id]


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """
    Execute an investigation agent with the given prompt (streaming SSE).

    Maintains persistent sessions to enable interrupts.
    """
    thread_id = request.thread_id or os.getenv("THREAD_ID", "default")

    # Convert images if provided
    images_list = None
    if request.images:
        images_list = [img.model_dump() for img in request.images]
        logger.info(f"Received {len(images_list)} image(s) for thread {thread_id}")

    # Get or create session BEFORE StreamingResponse
    session = await get_or_create_session(thread_id)

    async def stream():
        try:
            logger.info(f"Starting execution for thread {thread_id}")
            event_count = 0

            async for event in session.execute(request.prompt, images=images_list):
                event_count += 1
                if isinstance(event, StreamEvent):
                    yield event.to_sse()
                else:
                    yield f"data: {event}\n\n"

            logger.info(
                f"Execution completed: {event_count} events for thread {thread_id}"
            )

        except Exception as e:
            logger.error(f"Execution error for {thread_id}: {e}")
            err = error_event(thread_id, f"Execution failed: {e}", recoverable=False)
            yield err.to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/interrupt")
async def interrupt(request: InterruptRequest):
    """
    Interrupt the current execution and stop.

    After interrupt, new messages can be sent via execute endpoint.
    """
    thread_id = request.thread_id

    async def stream():
        try:
            async with _session_lock:
                if thread_id not in _sessions:
                    err = error_event(
                        thread_id, "No active session found", recoverable=False
                    )
                    yield err.to_sse()
                    return
                session = _sessions[thread_id]

            async for event in session.interrupt():
                if isinstance(event, StreamEvent):
                    yield event.to_sse()
                else:
                    yield f"data: {event}\n\n"

        except Exception as e:
            err = error_event(thread_id, f"Interrupt failed: {e}", recoverable=False)
            yield err.to_sse()

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
    answers = request.answers

    async with _session_lock:
        if thread_id not in _sessions:
            raise HTTPException(404, f"No active session for {thread_id}")
        session = _sessions[thread_id]

    try:
        await session.provide_answer(answers)
        return {"status": "ok", "thread_id": thread_id}
    except Exception as e:
        raise HTTPException(400, f"Failed to provide answer: {e}")


@app.post("/cleanup")
async def cleanup_session(thread_id: str):
    """Manually cleanup a session."""
    async with _session_lock:
        if thread_id in _sessions:
            session = _sessions.pop(thread_id)
            await session.close()
            return {"status": "cleaned", "thread_id": thread_id}
        return {"status": "not_found", "thread_id": thread_id}


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up all sessions on shutdown."""
    async with _session_lock:
        for session in _sessions.values():
            await session.close()
        _sessions.clear()


def run_server():
    """Run the sandbox server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="info")


if __name__ == "__main__":
    run_server()
