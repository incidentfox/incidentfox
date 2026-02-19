#!/usr/bin/env python3
"""
IncidentFox Investigation Server (Simple Mode)

Runs the agent in-process without K8s sandboxes.
For local testing and evaluation only - no isolation.

⚠️  Security Warning: This mode runs agent directly in the server process.
    - No filesystem isolation
    - No network isolation
    - No resource limits
    - Use only for trusted prompts on your own machine
    - For production, use server.py with K8s sandboxes

Usage:
    export USE_SIMPLE_MODE=true
    python server_simple.py
"""

import logging
import os
import secrets
import time
import uuid
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from events import error_event, result_event
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()

# File proxy: token -> download info mapping
_file_download_tokens: Dict[str, dict] = {}
_FILE_TOKEN_TTL_SECONDS = 3600  # 1 hour

import asyncio
from typing import AsyncIterator

# Thread ID -> background task mapping
_background_tasks: Dict[str, asyncio.Task] = {}
_message_queues: Dict[str, asyncio.Queue] = {}  # Queue for sending prompts
_response_queues: Dict[str, asyncio.Queue] = {}  # Queue for receiving events

app = FastAPI(
    title="IncidentFox Investigation Server (Simple Mode)",
    description="AI SRE agent for incident investigation - in-process mode (no sandboxes)",
    version="0.3.0",
)


class ImageData(BaseModel):
    type: str = "base64"
    media_type: str
    data: str
    filename: Optional[str] = None


class FileAttachment(BaseModel):
    filename: str
    size: int
    media_type: str
    download_url: str
    auth_header: str


class InvestigateRequest(BaseModel):
    prompt: str
    thread_id: Optional[str] = None
    images: Optional[List[ImageData]] = None
    file_attachments: Optional[List[FileAttachment]] = None


class InterruptRequest(BaseModel):
    thread_id: str


class AnswerRequest(BaseModel):
    thread_id: str
    answers: Dict[str, str]


@app.get("/")
async def root():
    return {
        "service": "IncidentFox Investigation Server",
        "mode": "simple",
        "version": "0.3.0",
        "warning": "No isolation - for local testing only",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "mode": "simple",
        "active_sessions": len(_background_tasks),
    }


def _get_proxy_base_url() -> str:
    """Get the base URL for file proxy that agent can access."""
    if os.getenv("ROUTER_LOCAL_PORT"):
        return "http://host.docker.internal:8000"

    service_name = os.getenv("K8S_SERVICE_NAME", "incidentfox-server-svc")
    namespace = os.getenv("K8S_NAMESPACE", "default")
    return f"http://{service_name}.{namespace}.svc.cluster.local:8000"


@app.get("/proxy/files/{token}")
async def proxy_file(token: str, request: Request):
    """
    File proxy endpoint - streams files from external sources (e.g., Slack).
    Allows agents to download files without having credentials.
    """
    # Cleanup expired tokens
    now = time.time()
    expired = [
        t
        for t, info in _file_download_tokens.items()
        if now - info["created_at"] > _FILE_TOKEN_TTL_SECONDS
    ]
    for t in expired:
        del _file_download_tokens[t]

    if token not in _file_download_tokens:
        raise HTTPException(404, "Token not found or expired")

    info = _file_download_tokens[token]
    del _file_download_tokens[token]  # Single-use token

    async def stream_file():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                async with client.stream(
                    "GET",
                    info["download_url"],
                    headers={"Authorization": info["auth_header"]},
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except Exception as e:
            logger.error(f"Failed to proxy file: {e}")
            raise HTTPException(500, f"Failed to download file: {e}")

    return StreamingResponse(
        stream_file(),
        media_type=info.get("media_type", "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{info["filename"]}"',
        },
    )


async def agent_background_task(thread_id: str):
    """
    Background task that keeps ClaudeSDKClient alive for multi-turn conversations.
    Processes messages from queue and sends responses back.
    """
    import json

    from agent import InteractiveAgentSession

    logger.info(f"[BG] Starting background agent task for thread {thread_id}")

    # Optionally load team config from config-service
    team_config = None
    if os.getenv("CONFIG_SERVICE_URL"):
        try:
            from config import load_team_config

            team_config = load_team_config()
            logger.info(
                f"[BG] Loaded team config: {len(team_config.agents)} agents, "
                f"{len(team_config.business_context)} chars business context"
            )
        except Exception as e:
            logger.warning(f"[BG] Failed to load team config (continuing without): {e}")

    session = InteractiveAgentSession(thread_id=thread_id, team_config=team_config)
    await session.start()
    logger.info(f"[BG] Session started for thread {thread_id}")

    message_queue = _message_queues[thread_id]
    response_queue = _response_queues[thread_id]

    try:
        while True:
            # Wait for next message
            logger.info(f"[BG] Waiting for message on thread {thread_id}")
            message = await message_queue.get()

            if message is None:  # Shutdown signal
                logger.info(f"[BG] Shutdown signal received for thread {thread_id}")
                break

            prompt = message.get("prompt")
            images = message.get("images")
            logger.info(
                f"[BG] Processing message for thread {thread_id}: {prompt[:50]}..."
            )
            if images:
                logger.info(f"[BG] Including {len(images)} image(s) in message")

            # Execute and stream events to response queue
            event_count = 0
            async for event in session.execute(prompt, images=images):
                event_count += 1
                event_type = event.type
                data = event.data

                # Send event to response queue
                await response_queue.put({"event": event_type, "data": data})

            # Signal completion
            await response_queue.put(None)
            logger.info(
                f"[BG] Completed message processing. Total events: {event_count}"
            )

    except Exception as e:
        logger.error(
            f"[BG] Background task failed for thread {thread_id}: {e}", exc_info=True
        )
        await response_queue.put({"error": str(e)})
    finally:
        # Cleanup
        if session.client:
            await session.cleanup()
        logger.info(f"[BG] Background task ended for thread {thread_id}")


def _download_file_attachments(file_downloads: list, thread_id: str):
    """
    Download file attachments directly using stored token info.

    In simple mode there's no sandbox, so we download files in-process
    using the credentials stored in _file_download_tokens. Files are saved
    to the agent's session directory at /tmp/sessions/{thread_id}/attachments/
    to match what the enriched prompt tells the agent.
    """
    from pathlib import Path

    # Must match agent.py's session directory for simple mode
    attachments_dir = Path(f"/tmp/sessions/{thread_id}/attachments")
    attachments_dir.mkdir(parents=True, exist_ok=True)

    for download in file_downloads:
        token = download["token"]
        token_info = _file_download_tokens.pop(token, None)
        if not token_info:
            logger.warning(f"Token not found for file {download['filename']}, skipping")
            continue

        safe_filename = Path(download["filename"]).name or "unnamed_file"
        file_path = attachments_dir / safe_filename

        # Handle duplicate filenames
        counter = 1
        original_stem = file_path.stem
        original_suffix = file_path.suffix
        while file_path.exists():
            file_path = attachments_dir / f"{original_stem}_{counter}{original_suffix}"
            counter += 1

        try:
            logger.info(
                f"Downloading {safe_filename} ({download.get('size', '?')} bytes) from Slack..."
            )
            with httpx.Client(timeout=httpx.Timeout(300.0)) as client:
                with client.stream(
                    "GET",
                    token_info["download_url"],
                    headers={"Authorization": token_info["auth_header"]},
                ) as response:
                    response.raise_for_status()
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=65536):
                            f.write(chunk)

            logger.info(f"Saved: {file_path}")
        except Exception as e:
            logger.error(f"Failed to download {safe_filename}: {e}")
            # Write error file so agent knows what happened
            error_path = attachments_dir / f"{file_path.name}.error"
            error_path.write_text(
                f"Download failed for: {safe_filename}\n"
                f"Error: {e}\n"
                f"\nThe file could not be downloaded from Slack. "
                f"Please ask the user to re-upload or share the content directly.\n"
            )


async def create_investigation_stream(
    thread_id: str,
    prompt: str,
    is_new: bool,
    images: Optional[List[dict]] = None,
    file_downloads: Optional[List[dict]] = None,
):
    """
    Create SSE stream by communicating with background agent task.
    """
    import datetime
    import json

    try:
        # Create background task if needed
        if thread_id not in _background_tasks:
            logger.info(f"Creating background task for thread {thread_id}")
            _message_queues[thread_id] = asyncio.Queue()
            _response_queues[thread_id] = asyncio.Queue()

            task = asyncio.create_task(agent_background_task(thread_id))
            _background_tasks[thread_id] = task

            # Give it a moment to start
            await asyncio.sleep(0.1)

        # Download file attachments directly (no sandbox, so download in-process)
        if file_downloads:
            _download_file_attachments(file_downloads, thread_id)

        # Send message to background task
        message_queue = _message_queues[thread_id]
        response_queue = _response_queues[thread_id]

        logger.info(f"Sending message to background task for thread {thread_id}")
        await message_queue.put({"prompt": prompt, "images": images})

        # Stream responses
        event_count = 0
        while True:
            response = await response_queue.get()

            if response is None:  # Completion signal
                break

            if "error" in response:
                error_payload = {
                    "type": "error",
                    "data": {"message": response["error"]},
                    "thread_id": thread_id,
                    "timestamp": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                }
                yield f"data: {json.dumps(error_payload)}\n\n"
                break

            event_count += 1
            event_type = response["event"]
            data = response["data"]

            # Emit SSE event in same format as sandbox mode
            # Format: data: {"type": "...", "data": {...}, "thread_id": "...", "timestamp": "..."}
            logger.info(f"Yielding event #{event_count}: {event_type}")
            event_payload = {
                "type": event_type,
                "data": data,
                "thread_id": thread_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            yield f"data: {json.dumps(event_payload)}\n\n"

        logger.info(f"Stream completed. Total events: {event_count}")

    except Exception as e:
        logger.error(f"Stream failed: {e}", exc_info=True)
        error_payload = {
            "type": "error",
            "data": {"message": str(e)},
            "thread_id": thread_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        yield f"data: {json.dumps(error_payload)}\n\n"


@app.post("/investigate")
async def investigate(request: InvestigateRequest):
    """
    Start or continue an investigation.

    Runs agent in-process (no sandbox isolation).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    thread_id = request.thread_id or f"thread-{uuid.uuid4().hex[:8]}"
    is_new = thread_id not in _background_tasks

    print(f"🔍 Investigation: thread={thread_id}, new={is_new}")

    # Handle file attachments
    file_downloads = None
    if request.file_attachments:
        file_downloads = []
        proxy_base_url = _get_proxy_base_url()

        for attachment in request.file_attachments:
            token = secrets.token_urlsafe(32)
            _file_download_tokens[token] = {
                "download_url": attachment.download_url,
                "auth_header": attachment.auth_header,
                "filename": attachment.filename,
                "media_type": attachment.media_type,
                "created_at": time.time(),
            }

            file_downloads.append(
                {
                    "token": token,
                    "filename": attachment.filename,
                    "size": attachment.size,
                    "proxy_url": f"{proxy_base_url}/proxy/files/{token}",
                }
            )

    # Convert images
    images = None
    if request.images:
        images = [
            {
                "type": img.type,
                "media_type": img.media_type,
                "data": img.data,
                "filename": img.filename,
            }
            for img in request.images
        ]

    stream = create_investigation_stream(
        thread_id,
        request.prompt,
        is_new,
        images,
        file_downloads,
    )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/interrupt")
async def interrupt(request: InterruptRequest):
    """
    Interrupt a running investigation.
    """
    import json

    if request.thread_id not in _active_sessions:
        raise HTTPException(404, f"No active session for thread {request.thread_id}")

    print(f"🛑 Interrupting thread {request.thread_id}")

    async def stream():
        try:
            session = _active_sessions[request.thread_id]
            session.interrupt()

            yield "event: interrupted\n"
            yield f"data: {json.dumps({'thread_id': request.thread_id})}\n\n"
        except Exception as e:
            logger.error(f"Interrupt failed: {e}", exc_info=True)
            yield "event: error\n"
            yield f"data: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/answer")
async def answer(request: AnswerRequest):
    """
    Send answer to agent's AskUserQuestion.
    """
    if request.thread_id not in _active_sessions:
        raise HTTPException(404, f"No active session for thread {request.thread_id}")

    print(f"📬 Forwarding answer to thread {request.thread_id}")

    session = _active_sessions[request.thread_id]
    # TODO: Implement answer forwarding when InteractiveAgentSession supports it

    return {"status": "ok", "thread_id": request.thread_id}


if __name__ == "__main__":
    import uvicorn

    print("=" * 70)
    print("⚠️  WARNING: Running in SIMPLE MODE (no sandboxes)")
    print("=" * 70)
    print()
    print("This mode runs the agent directly in the server process.")
    print("Use only for local testing with trusted prompts.")
    print()
    print("For production deployment, use server.py with K8s sandboxes.")
    print("=" * 70)
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)
