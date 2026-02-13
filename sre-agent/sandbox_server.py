#!/usr/bin/env python3
"""
Sandbox Server - Runs inside the sandbox container on port 8888

This server exposes endpoints for executing and interrupting investigations.
It maintains persistent ClaudeSDKClient sessions per thread_id to enable interrupts.

Streams structured events via SSE (Server-Sent Events) for slack-bot consumption.
"""

import asyncio
import os

# Add /app to path for imports
import sys
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, "/app")
from events import StreamEvent, error_event

from agent import InteractiveAgentSession, OpenHandsAgentSession, create_agent_session

app = FastAPI(
    title="IncidentFox Sandbox Runtime",
    description="Executes investigation agents in isolated sandbox with interrupt support",
    version="2.0.0",
)

# Global session manager: thread_id -> Agent session (InteractiveAgentSession or OpenHandsAgentSession)
_sessions: Dict[str, InteractiveAgentSession | OpenHandsAgentSession] = {}
_session_lock = asyncio.Lock()


class ImageData(BaseModel):
    """Image data for multimodal input."""

    type: str = "base64"  # Currently only base64 supported
    media_type: str  # e.g., "image/png", "image/jpeg"
    data: str  # Base64-encoded image data
    filename: Optional[str] = None


class FileDownload(BaseModel):
    """File download info for proxy-based download."""

    token: str  # Secure download token
    filename: str  # Original filename
    size: int  # File size in bytes
    media_type: str  # MIME type
    proxy_url: (
        str  # Full URL to download from (e.g., http://server:8000/proxy/files/{token})
    )


class ExecuteRequest(BaseModel):
    """Request to execute an investigation."""

    prompt: str
    thread_id: Optional[str] = None
    images: Optional[List[ImageData]] = None  # Optional attached images
    file_downloads: Optional[List[FileDownload]] = None  # Files to download via proxy


class InterruptRequest(BaseModel):
    """Request to interrupt the investigation."""

    thread_id: str


class AnswerRequest(BaseModel):
    """Request to provide answer to AskUserQuestion."""

    thread_id: str
    answers: dict


class ClaimRequest(BaseModel):
    """Request to claim a warm sandbox by injecting JWT."""

    jwt_token: str
    thread_id: str
    tenant_id: str
    team_id: str


class ExecuteResponse(BaseModel):
    """Response from executing an investigation."""

    stdout: str
    stderr: str
    exit_code: int


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns claim status for warm pool sandboxes.
    A sandbox is 'claimed' when JWT has been injected via /claim endpoint.
    """
    from pathlib import Path

    jwt_path = Path("/tmp/sandbox-jwt")
    claimed = jwt_path.exists() and jwt_path.read_text().strip() != ""

    return {
        "status": "healthy",
        "service": "incidentfox-sandbox",
        "active_sessions": len(_sessions),
        "claimed": claimed,
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


@app.post("/claim")
async def claim_sandbox(request: ClaimRequest):
    """
    Claim a warm sandbox by injecting JWT and setting context.

    This endpoint is called by the SandboxManager after a SandboxClaim
    binds to a warm pod. It:
    1. Writes JWT to /tmp/sandbox-jwt (read by Envoy Lua filter)
    2. Sets environment variables for tenant context

    Once claimed, the sandbox is ready for use and Envoy will inject
    the JWT in ext_authz requests.
    """
    import stat
    from pathlib import Path

    jwt_path = Path("/tmp/sandbox-jwt")

    # Prevent re-claiming an already-claimed sandbox
    if jwt_path.exists() and jwt_path.read_text().strip():
        raise HTTPException(
            status_code=409,
            detail="Sandbox already claimed",
        )

    # Write JWT to file (Envoy Lua filter reads this on each request)
    jwt_path.write_text(request.jwt_token)
    jwt_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only

    # Set environment variables for tenant context
    # These are used by the agent for logging and context
    os.environ["THREAD_ID"] = request.thread_id
    os.environ["INCIDENTFOX_TENANT_ID"] = request.tenant_id
    os.environ["INCIDENTFOX_TEAM_ID"] = request.team_id

    print(
        f"🔑 [CLAIM] Sandbox claimed for thread {request.thread_id} "
        f"(tenant={request.tenant_id}, team={request.team_id})"
    )

    return {
        "status": "claimed",
        "thread_id": request.thread_id,
        "tenant_id": request.tenant_id,
        "team_id": request.team_id,
    }


async def get_or_create_session(
    thread_id: str,
) -> InteractiveAgentSession | OpenHandsAgentSession:
    """
    Get existing session or create new one for thread_id.

    Uses create_agent_session() factory function which respects LLM_PROVIDER env var:
    - LLM_PROVIDER=claude (default): Uses Claude Agent SDK
    - LLM_PROVIDER=openhands: Uses OpenHands SDK for multi-LLM support

    Args:
        thread_id: Investigation thread ID

    Returns:
        Agent session instance (InteractiveAgentSession or OpenHandsAgentSession)
    """
    async with _session_lock:
        if thread_id not in _sessions:
            # Create new session using factory
            session = create_agent_session(thread_id)
            await session.start()
            _sessions[thread_id] = session
        return _sessions[thread_id]


def _download_files_from_proxy(
    file_downloads: List[FileDownload], thread_id: str
) -> List[str]:
    """
    Download file attachments from the proxy server into the sandbox filesystem.

    Files are saved to /workspace/attachments/{filename}
    During download, progress is written to: /workspace/attachments/{filename}.progress
    If download fails, an error file is written: /workspace/attachments/{filename}.error

    This downloads files via the sre-agent server's proxy endpoint, which injects
    the necessary authentication. The sandbox never sees the actual credentials.

    Args:
        file_downloads: List of file download info with proxy URLs
        thread_id: Thread ID for logging

    Returns:
        List of saved file paths (successful downloads only)
    """
    import time
    from pathlib import Path

    import httpx

    def format_size(bytes_val: int) -> str:
        """Format bytes as human-readable string."""
        if bytes_val >= 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"
        elif bytes_val >= 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.1f} KB"
        return f"{bytes_val} bytes"

    def write_progress(
        progress_path: Path,
        filename: str,
        downloaded: int,
        total: int,
        start_time: float,
    ):
        """Write progress file (overwrites each time to avoid growth)."""
        elapsed = time.time() - start_time
        percent = (downloaded / total * 100) if total > 0 else 0
        speed = downloaded / elapsed if elapsed > 0 else 0
        eta = (total - downloaded) / speed if speed > 0 else 0

        progress_path.write_text(
            f"Downloading: {filename}\n"
            f"Progress: {format_size(downloaded)} / {format_size(total)} ({percent:.1f}%)\n"
            f"Speed: {format_size(int(speed))}/s\n"
            f"ETA: {int(eta)}s\n"
            f"Elapsed: {int(elapsed)}s\n"
        )

    # Create attachments directory
    attachments_dir = Path("/workspace/attachments")
    attachments_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for download in file_downloads:
        # Sanitize filename (remove path traversal attempts)
        safe_filename = Path(download.filename).name
        if not safe_filename:
            safe_filename = "unnamed_file"

        # Determine save path
        file_path = attachments_dir / safe_filename

        # Handle duplicate filenames by adding suffix
        counter = 1
        original_stem = file_path.stem
        original_suffix = file_path.suffix
        while (
            file_path.exists() or (attachments_dir / f"{file_path.name}.error").exists()
        ):
            file_path = attachments_dir / f"{original_stem}_{counter}{original_suffix}"
            counter += 1

        error_path = attachments_dir / f"{file_path.name}.error"
        progress_path = attachments_dir / f"{file_path.name}.progress"

        try:
            print(
                f"📥 [SANDBOX] Downloading {download.filename} ({format_size(download.size)}) from proxy..."
            )
            print(f"    URL: {download.proxy_url}")

            start_time = time.time()

            # Download from proxy with streaming (handles large files)
            with httpx.Client(timeout=httpx.Timeout(300.0)) as client:
                with client.stream("GET", download.proxy_url) as response:
                    if response.status_code != 200:
                        error_msg = f"HTTP {response.status_code}: Failed to download from proxy"
                        print(
                            f"⚠️ [SANDBOX] Failed to download {download.filename}: {error_msg}"
                        )
                        # Write error file so agent knows what happened
                        error_path.write_text(
                            f"Download failed for: {download.filename}\n"
                            f"Size: {format_size(download.size)}\n"
                            f"Error: {error_msg}\n"
                        )
                        continue

                    # Stream to file with progress updates
                    bytes_written = 0
                    last_progress_update = 0
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_bytes(
                            chunk_size=65536
                        ):  # 64KB chunks
                            f.write(chunk)
                            bytes_written += len(chunk)

                            # Update progress file every 500KB or 1 second
                            if bytes_written - last_progress_update >= 512 * 1024:
                                write_progress(
                                    progress_path,
                                    download.filename,
                                    bytes_written,
                                    download.size,
                                    start_time,
                                )
                                last_progress_update = bytes_written

            # Remove progress file on success
            if progress_path.exists():
                progress_path.unlink()

            elapsed = time.time() - start_time
            speed = bytes_written / elapsed if elapsed > 0 else 0
            saved_paths.append(str(file_path))
            print(
                f"✅ [SANDBOX] Saved: {file_path} ({format_size(bytes_written)}) in {elapsed:.1f}s ({format_size(int(speed))}/s)"
            )

        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ [SANDBOX] Failed to download {download.filename}: {error_msg}")
            # Clean up progress file
            if progress_path.exists():
                try:
                    progress_path.unlink()
                except Exception:
                    pass
            # Write error file so agent knows what happened
            try:
                error_path.write_text(
                    f"Download failed for: {download.filename}\n"
                    f"Size: {format_size(download.size)}\n"
                    f"Error: {error_msg}\n"
                    f"\nThe file could not be downloaded from Slack. "
                    f"Please ask the user to re-upload or share the content directly.\n"
                )
            except Exception:
                pass  # Best effort

    return saved_paths


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """
    Execute an investigation agent with the given prompt (streaming SSE).

    This endpoint is called by the SandboxManager via the Router.
    Maintains persistent ClaudeSDKClient sessions to enable interrupts.

    Per SDK docs, sessions can continue after interrupt() without recreation.

    Returns a streaming SSE response with structured JSON events.
    """
    from fastapi.responses import StreamingResponse

    # Get thread_id from env or request
    thread_id = request.thread_id or os.getenv("THREAD_ID", "default")

    try:
        # Download file attachments from proxy BEFORE starting agent
        if request.file_downloads:
            print(
                f"📎 [SANDBOX] Downloading {len(request.file_downloads)} file(s) for thread {thread_id}"
            )
            saved_paths = _download_files_from_proxy(request.file_downloads, thread_id)
            print(f"📎 [SANDBOX] Downloaded {len(saved_paths)} file(s): {saved_paths}")

        # Convert images to list of dicts if provided
        images_list = None
        if request.images:
            images_list = [img.model_dump() for img in request.images]
            print(
                f"📷 [SANDBOX] Received {len(images_list)} image(s) for thread {thread_id}"
            )

        # CRITICAL: Get or create session BEFORE StreamingResponse
        # Otherwise FastAPI sends response headers before session exists, causing race conditions
        # Retry session creation — on freshly-replenished warm pool pods, envoy sidecar
        # may not be ready yet, causing transient connection errors to the LLM proxy.
        import asyncio

        session = None
        for attempt in range(3):
            try:
                session = await get_or_create_session(thread_id)
                break
            except Exception as e:
                if attempt < 2:
                    delay = 1.0 * (2**attempt)
                    print(
                        f"⚠️ [SANDBOX] Session creation attempt {attempt + 1}/3 failed for {thread_id}, "
                        f"retrying in {delay}s... ({e})"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
    except Exception as e:
        import traceback

        print(
            f"❌ [SANDBOX] Pre-stream setup failed for {thread_id}: {e}\n{traceback.format_exc()}"
        )
        # Return error as SSE stream instead of raw 500
        err = error_event(
            thread_id,
            f"Sandbox setup failed: {e}",
            recoverable=False,
        )

        async def error_stream():
            yield err.to_sse()

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async def stream():
        try:
            print(f"🔍 [SANDBOX-STREAM] Starting stream for thread {thread_id}")
            event_count = 0
            # Stream structured events as SSE
            async for event in session.execute(request.prompt, images=images_list):
                event_count += 1
                if isinstance(event, StreamEvent):
                    print(
                        f"🔍 [SANDBOX-STREAM] Event #{event_count}: {event.type} for thread {thread_id}"
                    )
                    yield event.to_sse()
                else:
                    print(
                        f"🔍 [SANDBOX-STREAM] Event #{event_count}: raw string for thread {thread_id}"
                    )
                    # Fallback for any raw strings (shouldn't happen)
                    yield f"data: {event}\n\n"
            print(
                f"✅ [SANDBOX-STREAM] Stream completed with {event_count} events for thread {thread_id}"
            )

        except Exception as e:
            import traceback

            error_msg = str(e)

            # Provide user-friendly message for known SDK buffer issues
            if "buffer size" in error_msg.lower() or "1048576" in error_msg:
                error_msg = "A subagent produced too much output (SDK 1MB buffer limit). Try a simpler task or avoid parallel subagents."

            err = error_event(
                thread_id, f"Execution failed: {error_msg}", recoverable=False
            )
            yield err.to_sse()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.post("/interrupt")
async def interrupt(request: InterruptRequest):
    """
    Interrupt the current execution and stop.

    This allows users to stop a long-running task mid-execution.
    After interrupt, new messages should be sent via the normal execute endpoint.

    Returns a streaming SSE response with structured events.

    Note: This follows Cursor's UX - interrupt just stops, new messages
    are queued separately.
    """
    from fastapi.responses import StreamingResponse

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

            # Stream interrupt events
            async for event in session.interrupt():
                if isinstance(event, StreamEvent):
                    yield event.to_sse()
                else:
                    yield f"data: {event}\n\n"

        except Exception as e:
            error_msg = str(e)
            if "buffer size" in error_msg.lower() or "1048576" in error_msg:
                error_msg = "Buffer overflow during interrupt. Please try again."
            err = error_event(
                thread_id, f"Interrupt failed: {error_msg}", recoverable=False
            )
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
    """
    Receive answer to AskUserQuestion from main server.
    Wakes up the waiting can_use_tool callback in the agent session.
    """
    thread_id = request.thread_id
    answers = request.answers

    async with _session_lock:
        if thread_id not in _sessions:
            raise HTTPException(404, f"No active session for {thread_id}")

        session = _sessions[thread_id]

    # Use the unified provide_answer method (works for both providers)
    try:
        await session.provide_answer(answers)
        return {"status": "ok", "thread_id": thread_id}
    except Exception as e:
        raise HTTPException(400, f"Failed to provide answer: {str(e)}")


@app.post("/cleanup")
async def cleanup_session(thread_id: str):
    """
    Manually cleanup a session (for testing/debugging).
    Sessions are automatically cleaned up when sandbox is destroyed.
    """
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


if __name__ == "__main__":
    # Run on port 8888 (agent-sandbox standard)
    uvicorn.run(app, host="0.0.0.0", port=8888, log_level="info")
