#!/usr/bin/env python3
"""
Test the EXACT production pattern:
- Async background task function
- Synchronous httpx calls inside the async function

This mimics how production webhook handlers work.
"""

import json
import time
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import uvicorn


def _log(event: str, **fields: Any) -> None:
    try:
        payload = {"service": "test", "event": event, **fields}
        print(json.dumps(payload, default=str), flush=True)
    except Exception:
        print(f"{event} {fields}", flush=True)


class RequestIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = str(uuid.uuid4())[:8]
        _log("mw_start", rid=rid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                _log("mw_response_start", rid=rid, status=message.get("status"))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            _log("mw_complete", rid=rid)
        except Exception as e:
            _log("mw_error", rid=rid, error=str(e))
            raise


app = FastAPI()


# Simulated config service client (like production)
class ConfigServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def lookup_routing(self, **kwargs) -> dict:
        """Synchronous HTTP call (like production)."""
        _log("cfg_lookup_routing_start")
        # Use sync httpx client like production
        with httpx.Client(timeout=10.0) as client:
            try:
                # Make a real HTTP call (to httpbin as a test)
                resp = client.get("https://httpbin.org/delay/1")
                _log("cfg_lookup_routing_response", status=resp.status_code)
            except Exception as e:
                _log("cfg_lookup_routing_error", error=str(e))
        _log("cfg_lookup_routing_done")
        return {"found": True, "org_id": "test-org", "team_node_id": "test-team"}


# Simulated agent API client (like production)
class AgentApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def run_agent(self, **kwargs) -> dict:
        """Synchronous HTTP call (like production)."""
        _log("agent_run_start")
        with httpx.Client(timeout=10.0) as client:
            try:
                resp = client.get("https://httpbin.org/delay/1")
                _log("agent_run_response", status=resp.status_code)
            except Exception as e:
                _log("agent_run_error", error=str(e))
        _log("agent_run_done")
        return {"success": True}


@app.on_event("startup")
async def startup():
    app.state.config_service = ConfigServiceClient("http://config:8080")
    app.state.agent_api = AgentApiClient("http://agent:8080")
    _log("app_startup")


async def _process_webhook_production_pattern(
    request: Request,
    alert_data: dict,
    event_type: str,
    alert_source_id: str,
) -> None:
    """
    This mimics _process_incidentio_webhook EXACTLY:
    - Async function
    - Accesses request.app.state
    - Makes synchronous HTTP calls via httpx.Client
    """
    _log("task_started", alert_source_id=alert_source_id, event_type=event_type)

    try:
        cfg = request.app.state.config_service
        agent_api = request.app.state.agent_api

        # Synchronous routing lookup (like production)
        _log("task_calling_routing")
        routing = cfg.lookup_routing(alert_source_id=alert_source_id)
        _log("task_routing_result", routing=routing)

        if not routing.get("found"):
            _log("task_no_routing")
            return

        # Synchronous agent call (like production)
        _log("task_calling_agent")
        result = agent_api.run_agent(message="test")
        _log("task_agent_result", result=result)

        _log("task_completed")

    except Exception as e:
        _log("task_failed", error=str(e))


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    alert_data = {"title": "Test Alert"}
    alert_source_id = "test-source"
    event_type = "public_alert.alert_created_v1"

    _log("endpoint_adding_task", alert_source_id=alert_source_id)

    background.add_task(
        _process_webhook_production_pattern,
        request=request,
        alert_data=alert_data,
        event_type=event_type,
        alert_source_id=alert_source_id,
    )

    _log("endpoint_task_added", tasks_count=len(background.tasks))

    return JSONResponse(content={"ok": True})


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    _log("starting")
    app.add_middleware(RequestIdMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8095, log_level="info")
