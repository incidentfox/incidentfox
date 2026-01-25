#!/usr/bin/env python3
"""
Test if passing Request object to background task breaks things.
"""

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
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


# Test 1: Background task WITHOUT Request
async def task_without_request(msg: str) -> None:
    _log("task_no_req_started", msg=msg)
    await asyncio.sleep(1)
    _log("task_no_req_done", msg=msg)


# Test 2: Background task WITH Request (production pattern)
async def task_with_request(request: Request, msg: str) -> None:
    _log("task_with_req_started", msg=msg)
    await asyncio.sleep(1)
    _log("task_with_req_done", msg=msg)


# Test 3: Background task WITH Request, accessing app.state
async def task_accessing_state(request: Request, msg: str) -> None:
    _log("task_state_started", msg=msg)
    # Access app.state like production code does
    has_state = hasattr(request.app, 'state')
    _log("task_state_access", has_state=has_state)
    await asyncio.sleep(1)
    _log("task_state_done", msg=msg)


@app.post("/test1")
async def test_without_request(background: BackgroundTasks):
    _log("endpoint1_start")
    background.add_task(task_without_request, msg="no-request")
    _log("endpoint1_done", tasks=len(background.tasks))
    return {"test": 1}


@app.post("/test2")
async def test_with_request(request: Request, background: BackgroundTasks):
    _log("endpoint2_start")
    background.add_task(task_with_request, request=request, msg="with-request")
    _log("endpoint2_done", tasks=len(background.tasks))
    return {"test": 2}


@app.post("/test3")
async def test_accessing_state(request: Request, background: BackgroundTasks):
    _log("endpoint3_start")
    background.add_task(task_accessing_state, request=request, msg="state-access")
    _log("endpoint3_done", tasks=len(background.tasks))
    return {"test": 3}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    _log("starting")
    app.add_middleware(RequestIdMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8094, log_level="info")
