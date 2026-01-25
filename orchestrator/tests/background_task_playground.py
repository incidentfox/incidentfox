#!/usr/bin/env python3
"""
Minimal playground to debug FastAPI BackgroundTasks with ASGI middleware.

This reproduces the exact setup we have in production to isolate the issue.

Run with:
    cd orchestrator
    python tests/background_task_playground.py

Then test with:
    curl -X POST http://localhost:8090/webhook -H "Content-Type: application/json" -d '{"test": "data"}'
"""

import asyncio
import logging
import time
import uuid
from typing import Callable

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# Configure logging to see everything
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI()


# =============================================================================
# Pure ASGI Middleware (same as our production code)
# =============================================================================
class RequestIdMiddleware:
    """Pure ASGI middleware for request ID and logging."""

    def __init__(self, app):
        self.app = app
        logger.info("RequestIdMiddleware initialized")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = str(uuid.uuid4())[:8]
        method = scope.get("method", "")
        path = scope.get("path", "")
        start = time.time()
        status_code = 500

        logger.info(f"[{rid}] >>> Request started: {method} {path}")

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                logger.info(f"[{rid}] Response status: {status_code}")
                # Add request ID to response headers
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode("utf-8")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            elapsed = time.time() - start
            logger.info(f"[{rid}] <<< Request completed: {method} {path} -> {status_code} ({elapsed:.3f}s)")
        except Exception as e:
            logger.error(f"[{rid}] !!! Request failed: {e}")
            raise


# =============================================================================
# Alternative: Starlette's call_next style (known to break BackgroundTasks)
# =============================================================================
# @app.middleware("http")
# async def http_middleware(request: Request, call_next):
#     """This style BREAKS BackgroundTasks - don't use!"""
#     rid = str(uuid.uuid4())[:8]
#     logger.info(f"[{rid}] >>> Request started")
#     response = await call_next(request)
#     logger.info(f"[{rid}] <<< Request completed")
#     return response


# =============================================================================
# Background Task Function
# =============================================================================
async def process_webhook_async(data: dict, task_id: str):
    """Simulates our webhook processing background task."""
    logger.info(f"[TASK {task_id}] *** BACKGROUND TASK STARTED ***")
    logger.info(f"[TASK {task_id}] Processing data: {data}")

    # Simulate some async work
    await asyncio.sleep(2)

    logger.info(f"[TASK {task_id}] *** BACKGROUND TASK COMPLETED ***")


# =============================================================================
# Webhook Endpoint (mirrors our production endpoint)
# =============================================================================
@app.post("/webhook")
async def webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
    """Webhook endpoint that schedules a background task."""
    task_id = str(uuid.uuid4())[:8]

    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info(f"[ENDPOINT] Received webhook, scheduling background task {task_id}")

    # Schedule background task (same pattern as our production code)
    background_tasks.add_task(process_webhook_async, body, task_id)

    logger.info(f"[ENDPOINT] Background task {task_id} added, returning response")

    # Return immediately (background task should run after response)
    return JSONResponse(
        content={"status": "accepted", "task_id": task_id},
        status_code=200
    )


@app.get("/health")
async def health():
    """Health check endpoint (no background tasks)."""
    logger.info("[ENDPOINT] Health check")
    return {"status": "healthy"}


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    # Toggle middleware on/off for testing
    USE_MIDDLEWARE = True

    if USE_MIDDLEWARE:
        logger.info("=" * 60)
        logger.info("RUNNING WITH PURE ASGI MIDDLEWARE")
        logger.info("=" * 60)
        app.add_middleware(RequestIdMiddleware)
    else:
        logger.info("=" * 60)
        logger.info("RUNNING WITHOUT MIDDLEWARE")
        logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")
