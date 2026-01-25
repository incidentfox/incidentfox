#!/usr/bin/env python3
"""
Test with ASYNC sleep in background task.

The issue might be that sync time.sleep() blocks the event loop.
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
        method = scope.get("method", "")
        path = scope.get("path", "")
        start = time.time()

        _log("middleware_start", rid=rid, method=method, path=path)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                _log("middleware_response_start", rid=rid, status=message.get("status"))
            elif message["type"] == "http.response.body":
                _log("middleware_response_body", rid=rid)
            await send(message)

        try:
            _log("middleware_calling_app", rid=rid)
            await self.app(scope, receive, send_wrapper)
            _log("middleware_app_returned", rid=rid, elapsed=f"{time.time()-start:.3f}s")
        except Exception as e:
            _log("middleware_error", rid=rid, error=str(e))
            raise


app = FastAPI()


@app.on_event("startup")
async def startup():
    _log("app_startup")


async def _process_webhook_async(alert_source_id: str) -> None:
    """Background task with ASYNC sleep."""
    _log("task_started", alert_source_id=alert_source_id)

    # Async sleep - doesn't block event loop
    await asyncio.sleep(2)

    _log("task_completed", alert_source_id=alert_source_id)


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    alert_source_id = "test-source"

    _log("endpoint_adding_task")
    background.add_task(_process_webhook_async, alert_source_id=alert_source_id)
    _log("endpoint_task_added", tasks_count=len(background.tasks))

    return JSONResponse(content={"ok": True})


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    _log("starting_server")
    app.add_middleware(RequestIdMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8093, log_level="info")
