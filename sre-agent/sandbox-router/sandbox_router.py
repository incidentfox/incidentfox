# Copyright 2025 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

# Initialize the FastAPI application
app = FastAPI()

# Configuration
DEFAULT_SANDBOX_PORT = 8888
DEFAULT_NAMESPACE = "default"

# Retry configuration for handling DNS propagation delays and pod startup
# Headless Services for new sandboxes can take 5-10s for DNS to propagate
RETRY_COUNT = 8
RETRY_BASE_DELAY = 1.0  # seconds, with exponential backoff capped at 4s
# For streaming SSE, use separate connect/read/write/pool timeouts
# connect: 30s to establish connection
# read: None - no timeout between SSE events (agent may think for minutes)
# write: None - no timeout for writing requests
# pool: None - no timeout for acquiring connection from pool
client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=30.0, read=None, write=None, pool=None)
)


@app.get("/healthz")
async def health_check():
    """A simple health check endpoint that always returns 200 OK."""
    return {"status": "ok"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, full_path: str):
    """
    Receives all incoming requests, determines the target sandbox from headers,
    and asynchronously proxies the request to it.
    """
    sandbox_id = request.headers.get("X-Sandbox-ID")
    if not sandbox_id:
        raise HTTPException(status_code=400, detail="X-Sandbox-ID header is required.")

    # Dynamic discovery via headers
    namespace = request.headers.get("X-Sandbox-Namespace", DEFAULT_NAMESPACE)

    # Sanitize namespace to prevent DNS injection
    if not namespace.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid namespace format.")

    try:
        port = int(request.headers.get("X-Sandbox-Port", DEFAULT_SANDBOX_PORT))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid port format.")

    # Construct the K8s internal DNS name
    target_host = f"{sandbox_id}.{namespace}.svc.cluster.local"
    target_url = f"http://{target_host}:{port}/{full_path}"

    print(f"Proxying request for sandbox '{sandbox_id}' to URL: {target_url}")

    # Read request body once (can only be read once from the stream)
    request_body = await request.body()
    headers = {
        key: value for (key, value) in request.headers.items() if key.lower() != "host"
    }

    # Retry loop with exponential backoff for DNS propagation and pod startup
    last_error = None
    for attempt in range(RETRY_COUNT):
        try:
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=request_body,
            )

            resp = await client.send(req, stream=True)

            return StreamingResponse(
                content=resp.aiter_bytes(),
                status_code=resp.status_code,
                headers=resp.headers,
            )
        except httpx.ConnectError as e:
            last_error = e
            if attempt < RETRY_COUNT - 1:
                delay = min(
                    RETRY_BASE_DELAY * (2**attempt), 4.0
                )  # Exponential backoff capped at 4s
                print(
                    f"Connection to sandbox '{sandbox_id}' failed (attempt {attempt + 1}/{RETRY_COUNT}), "
                    f"retrying in {delay}s... Error: {e}"
                )
                await asyncio.sleep(delay)
            else:
                print(
                    f"ERROR: All {RETRY_COUNT} connection attempts to sandbox at {target_url} failed. "
                    f"Error: {e}"
                )
        except Exception as e:
            # Don't retry on non-connection errors
            print(f"An unexpected error occurred: {e}")
            raise HTTPException(
                status_code=500, detail="An internal error occurred in the proxy."
            )

    # All retries exhausted
    raise HTTPException(
        status_code=502,
        detail=f"Could not connect to the backend sandbox: {sandbox_id}",
    )
