#!/usr/bin/env python3
"""
Test background tasks WITH middleware enabled.

This tests if the pure ASGI middleware breaks background tasks
when combined with the realistic webhook pattern.

Run with:
    source /tmp/playground_venv/bin/activate
    python tests/background_task_with_middleware.py
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _log(event: str, **fields: Any) -> None:
    try:
        payload = {"service": "test", "event": event, **fields}
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


# =============================================================================
# Pure ASGI Middleware (same as production)
# =============================================================================
class RequestIdMiddleware:
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

        _log("middleware_request_started", rid=rid, method=method, path=path)

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            elapsed = time.time() - start
            _log("middleware_request_completed", rid=rid, status=status_code, elapsed_ms=int(elapsed*1000))
        except Exception as e:
            _log("middleware_request_failed", rid=rid, error=str(e))
            raise


app = FastAPI()


# Simulate app.state
class ConfigServiceClient:
    def lookup_routing(self, **kwargs):
        return {"found": True, "org_id": "test-org", "team_node_id": "test-team"}


class AgentApiClient:
    def run_agent(self, **kwargs):
        time.sleep(1)
        return {"success": True}


@app.on_event("startup")
async def startup():
    app.state.config_service = ConfigServiceClient()
    app.state.agent_api = AgentApiClient()


async def _process_webhook(
    request: Request,
    alert_source_id: str,
) -> None:
    """Background task that uses Request object."""
    _log("task_started", alert_source_id=alert_source_id)

    try:
        cfg = request.app.state.config_service
        agent_api = request.app.state.agent_api

        routing = cfg.lookup_routing(alert_source_id=alert_source_id)
        _log("task_routing_found", routing=routing)

        _log("task_calling_agent")
        result = agent_api.run_agent(message="test")
        _log("task_agent_completed", result=result)

        _log("task_completed")
    except Exception as e:
        _log("task_failed", error=str(e))


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    alert_source_id = "test-source"

    _log("webhook_adding_task", alert_source_id=alert_source_id)
    background.add_task(_process_webhook, request=request, alert_source_id=alert_source_id)
    _log("webhook_task_added", tasks_count=len(background.tasks))

    return JSONResponse(content={"ok": True})


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("TESTING WITH MIDDLEWARE ENABLED")
    logger.info("=" * 60)

    # ADD MIDDLEWARE
    app.add_middleware(RequestIdMiddleware)

    uvicorn.run(app, host="0.0.0.0", port=8092, log_level="info")
