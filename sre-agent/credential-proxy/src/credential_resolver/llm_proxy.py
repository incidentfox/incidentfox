"""LLM proxy route: translates Anthropic Messages API to any model via LiteLLM.

Handles:
- Claude models: pass-through to api.anthropic.com (no translation)
- All other models: translate Anthropic→OpenAI, call via litellm, translate back

This module is registered as a FastAPI router in main.py.
"""

import json
import logging
import os
from typing import AsyncIterator

import httpx
import litellm
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response, StreamingResponse

from .llm_stream import StreamTranslator
from .llm_translator import (
    anthropic_to_openai_request,
    openai_error_to_anthropic,
    openai_to_anthropic_response,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


# ---------------------------------------------------------------------------
# Model detection
# ---------------------------------------------------------------------------


def is_claude_model(model: str) -> bool:
    """Check if a model string refers to a Claude/Anthropic model."""
    m = model.lower()
    return m.startswith("claude") or m.startswith("anthropic/")


def get_provider_for_credentials(model: str) -> str:
    """Map model string to credential integration ID.

    Returns the integration name used in credential-resolver's
    load_env_credentials() / get_credentials().

    LiteLLM model naming conventions:
      - openai/gpt-4o, gpt-4o-mini, o1-*, o3-*  → "openai"
      - gemini/gemini-2.5-flash                   → "gemini"
      - azure_ai/<model>                            → "azure_ai"
      - azure/<deployment>                         → "azure"
      - bedrock/<model>                            → "bedrock"
      - mistral/<model>                            → "mistral"
      - cohere/<model>, command-r-*                → "cohere"
      - together_ai/<model>                        → "together_ai"
      - groq/<model>                               → "groq"
      - fireworks_ai/<model>                       → "fireworks_ai"
      - xai/<model>                                → "xai"
      - moonshot/<model>                           → "moonshot"
      - minimax/<model>                            → "minimax"
      - vertex_ai/<model>                          → "vertex_ai"
      - ollama/<model>                             → "ollama"
      - openrouter/<provider>/<model>              → "openrouter"
      - deepseek/<model>                           → "deepseek"
      - zai/<model>                                → "zai"
      - arcee/<model>                              → "arcee"
    """
    m = model.lower()
    if m.startswith(("claude", "anthropic/")):
        return "anthropic"
    if m.startswith(("openai/", "gpt-", "o1-", "o3-")):
        return "openai"
    if m.startswith("cloudflare_ai/"):
        return "cloudflare_ai"
    if m.startswith("custom_endpoint/"):
        return "custom_endpoint"
    if m.startswith("gemini/"):
        return "gemini"
    if m.startswith("azure_ai/"):
        return "azure_ai"
    if m.startswith("azure/"):
        return "azure"
    if m.startswith("bedrock/"):
        return "bedrock"
    if m.startswith("mistral/"):
        return "mistral"
    if m.startswith(("cohere/", "command-r")):
        return "cohere"
    if m.startswith("together_ai/"):
        return "together_ai"
    if m.startswith("groq/"):
        return "groq"
    if m.startswith("fireworks_ai/"):
        return "fireworks_ai"
    if m.startswith("xai/"):
        return "xai"
    if m.startswith("moonshot/"):
        return "moonshot"
    if m.startswith("minimax/"):
        return "minimax"
    if m.startswith("vertex_ai/"):
        return "vertex_ai"
    if m.startswith("ollama/"):
        return "ollama"
    if m.startswith(("or:", "openrouter/")):
        return "openrouter"
    if m.startswith("deepseek/"):
        return "deepseek"
    if m.startswith("qwen/"):
        return "qwen"
    if m.startswith("zai/"):
        return "zai"
    if m.startswith("arcee/"):
        return "arcee"
    # Default: try openrouter as catch-all for unknown models
    return "openrouter"


def get_api_key_for_provider(provider: str, creds: dict | None) -> str | None:
    """Extract API key from credentials dict for a provider."""
    if not creds:
        return None
    return creds.get("api_key")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.api_route("/v1/messages", methods=["POST"])
async def llm_proxy(request: Request):
    """Main LLM proxy endpoint.

    Receives Anthropic Messages API format (from Claude SDK),
    detects the target model, and either:
    - Passes through to Anthropic (for Claude models)
    - Translates and routes to other providers via LiteLLM
    """
    # 1. Extract tenant context from headers (set by ext_authz)
    tenant_id = request.headers.get("x-tenant-id", "local")
    team_id = request.headers.get("x-team-id", "local")

    # 2. Read and parse request body
    raw_body = await request.body()
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 3. Determine model with priority chain
    # Import here to avoid circular imports with main.py
    from .main import get_credentials

    # Priority 1: Per-tenant config from Config Service
    llm_config = await get_credentials(tenant_id, team_id, "llm")
    model = (llm_config or {}).get("model", "")

    # Priority 2: Deployment default (env var via ext_authz header or direct)
    if not model:
        model = request.headers.get("x-llm-model", "") or os.getenv("LLM_MODEL", "")

    # Priority 3: Body model field (SDK default — always claude-*)
    if not model:
        model = body.get("model", "")

    # Priority 4: Hardcoded default
    if not model:
        model = "claude-sonnet-4-20250514"

    is_streaming = body.get("stream", False)
    logger.info(
        f"LLM proxy: model={model}, streaming={is_streaming}, "
        f"tenant={tenant_id}, team={team_id}"
    )

    # 4. Route based on model
    if is_claude_model(model):
        return await _forward_to_anthropic(request, raw_body, is_streaming)
    else:
        return await _forward_to_provider(body, model, is_streaming, tenant_id, team_id)


@router.api_route("/v1/messages/count_tokens", methods=["POST"])
async def count_tokens_proxy(request: Request):
    """Token counting endpoint — forward to Anthropic or estimate."""
    model = request.headers.get("x-llm-model", "")
    if not model or is_claude_model(model):
        return await _forward_to_anthropic(
            request, await request.body(), is_streaming=False
        )
    # For non-Claude models, return a basic estimate
    # (exact counting requires provider-specific tokenizers)
    body = await request.json()
    messages = body.get("messages", [])
    # Rough estimate: 4 chars per token
    total_chars = sum(len(json.dumps(m.get("content", ""))) for m in messages)
    return Response(
        content=json.dumps({"input_tokens": total_chars // 4}),
        media_type="application/json",
    )


@router.api_route(
    "/api/event_logging/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def event_logging_proxy(path: str, request: Request):
    """Anthropic telemetry endpoint — forward for Claude, drop for others."""
    model = request.headers.get("x-llm-model", "")
    if not model or is_claude_model(model):
        return await _forward_to_anthropic(
            request, await request.body(), is_streaming=False
        )
    # For non-Claude models, silently accept and discard
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Anthropic pass-through
# ---------------------------------------------------------------------------


async def _forward_to_anthropic(
    request: Request,
    raw_body: bytes,
    is_streaming: bool,
) -> Response:
    """Forward request to Anthropic API unchanged (Claude models).

    The x-api-key header is already injected by ext_authz.
    """
    api_key = request.headers.get("x-api-key", "")
    anthropic_base = os.getenv("ANTHROPIC_UPSTREAM_URL", "https://api.anthropic.com")

    # Reconstruct the path
    target_url = f"{anthropic_base}{request.url.path}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
    }
    # Forward anthropic-beta if present
    beta = request.headers.get("anthropic-beta")
    if beta:
        headers["anthropic-beta"] = beta

    if is_streaming:
        return await _stream_passthrough(target_url, headers, raw_body)
    else:
        return await _sync_passthrough(target_url, headers, raw_body)


async def _stream_passthrough(
    url: str, headers: dict, body: bytes
) -> StreamingResponse:
    """Stream Anthropic response bytes through unmodified."""

    async def stream_generator() -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", url, headers=headers, content=body
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    yield error_body
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _sync_passthrough(url: str, headers: dict, body: bytes) -> Response:
    """Forward non-streaming request to Anthropic and return response."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, headers=headers, content=body)
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={
                "Content-Type": response.headers.get("Content-Type", "application/json")
            },
        )


# ---------------------------------------------------------------------------
# Non-Claude: translate + LiteLLM
# ---------------------------------------------------------------------------


async def _forward_to_provider(
    body: dict,
    model: str,
    is_streaming: bool,
    tenant_id: str,
    team_id: str,
) -> Response:
    """Translate Anthropic request, call LiteLLM, translate response back."""
    from .main import get_credentials

    # 1. Get credentials for the provider
    provider = get_provider_for_credentials(model)
    creds = await get_credentials(tenant_id, team_id, provider)
    api_key = get_api_key_for_provider(provider, creds)

    # Providers that don't use standard api_key
    no_api_key_providers = {"ollama", "vertex_ai"}
    # Bedrock: accepts either ABSK bearer token (api_key) or IAM creds
    if provider == "bedrock":
        has_bedrock_auth = (creds or {}).get("api_key") or (
            (creds or {}).get("aws_access_key_id")
            and (creds or {}).get("aws_secret_access_key")
        )
        if not has_bedrock_auth:
            logger.error(f"No credentials for Bedrock, tenant={tenant_id}")
            error = openai_error_to_anthropic(
                401,
                {
                    "error": {
                        "type": "authentication_error",
                        "message": "No Bedrock API key or IAM credentials configured",
                    }
                },
            )
            return Response(
                content=json.dumps(error),
                status_code=401,
                media_type="application/json",
            )
    elif provider not in no_api_key_providers and not api_key:
        logger.error(f"No API key for provider={provider}, tenant={tenant_id}")
        error = openai_error_to_anthropic(
            401,
            {
                "error": {
                    "type": "authentication_error",
                    "message": f"No API key configured for {provider}",
                }
            },
        )
        return Response(
            content=json.dumps(error),
            status_code=401,
            media_type="application/json",
        )

    # 2. Translate Anthropic request → OpenAI format
    openai_body = anthropic_to_openai_request(body)
    openai_body["model"] = model  # LiteLLM uses this to route

    logger.info(
        f"LLM proxy: translated request for model={model}, "
        f"messages={len(openai_body.get('messages', []))}, "
        f"tools={len(openai_body.get('tools', []))}"
    )

    # 3. Build litellm kwargs
    litellm_kwargs: dict = {
        "model": model,
        "messages": openai_body["messages"],
        "stream": is_streaming,
    }

    if api_key:
        litellm_kwargs["api_key"] = api_key

    # Pass optional params
    for key in (
        "max_tokens",
        "temperature",
        "top_p",
        "stop",
        "tools",
        "tool_choice",
        "stream_options",
    ):
        if key in openai_body:
            litellm_kwargs[key] = openai_body[key]

    # Provider-specific overrides
    if provider == "ollama":
        host = (creds or {}).get("host", "http://localhost:11434")
        litellm_kwargs["api_base"] = host
    elif provider == "azure":
        litellm_kwargs["api_base"] = (creds or {}).get("api_base", "")
        litellm_kwargs["api_version"] = (creds or {}).get("api_version", "2024-06-01")
    elif provider == "azure_ai":
        # Azure AI Foundry serverless deployments — OpenAI-compatible with custom base
        litellm_kwargs["api_base"] = (creds or {}).get("api_base", "")
    elif provider == "bedrock":
        bedrock_api_key = (creds or {}).get("api_key", "")
        if bedrock_api_key:
            # Bedrock API key (ABSK bearer token) — pass directly to LiteLLM
            litellm_kwargs["api_key"] = bedrock_api_key
        else:
            # Traditional IAM credentials
            litellm_kwargs.pop("api_key", None)
            litellm_kwargs["aws_access_key_id"] = (creds or {}).get(
                "aws_access_key_id", ""
            )
            litellm_kwargs["aws_secret_access_key"] = (creds or {}).get(
                "aws_secret_access_key", ""
            )
        litellm_kwargs["aws_region_name"] = (creds or {}).get(
            "aws_region_name", "us-east-1"
        )
    elif provider == "vertex_ai":
        litellm_kwargs.pop("api_key", None)  # Vertex AI uses GCP credentials
        litellm_kwargs["vertex_project"] = (creds or {}).get("project", "")
        litellm_kwargs["vertex_location"] = (creds or {}).get("location", "us-central1")
        # If service account JSON is provided, set it via env var for LiteLLM
        sa_json = (creds or {}).get("service_account_json", "")
        if sa_json:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = sa_json
    elif provider == "moonshot":
        # Moonshot/Kimi has an OpenAI-compatible API at api.moonshot.ai
        # Rewrite model from moonshot/<name> to openai/<name> for LiteLLM
        litellm_kwargs["api_base"] = "https://api.moonshot.ai/v1"
        model_name = model.split("/", 1)[1] if "/" in model else model
        litellm_kwargs["model"] = f"openai/{model_name}"
    elif provider == "minimax":
        # MiniMax has an OpenAI-compatible API at api.minimax.io
        litellm_kwargs["api_base"] = "https://api.minimax.io/v1"
        model_name = model.split("/", 1)[1] if "/" in model else model
        litellm_kwargs["model"] = f"openai/{model_name}"
    elif provider == "arcee":
        # Arcee AI has an OpenAI-compatible API at models.arcee.ai
        litellm_kwargs["api_base"] = "https://models.arcee.ai/v1"
        model_name = model.split("/", 1)[1] if "/" in model else model
        litellm_kwargs["model"] = f"openai/{model_name}"
    elif provider == "cloudflare_ai":
        # Cloudflare AI Gateway — OpenAI-compatible endpoint with special auth header
        # Model format: cloudflare_ai/<provider>/<model> e.g. cloudflare_ai/openai/gpt-4o
        api_base = (creds or {}).get("api_base", "")
        if api_base:
            if not api_base.rstrip("/").endswith("/compat"):
                api_base = api_base.rstrip("/") + "/compat"
            litellm_kwargs["api_base"] = api_base
        # Strip "cloudflare_ai/" prefix — remaining is the provider/model for CF
        model_name = model.split("/", 1)[1] if "/" in model else model
        litellm_kwargs["model"] = f"openai/{model_name}"
        # CF auth: cf-aig-authorization header for gateway auth
        cf_token = (creds or {}).get("api_key", "")
        extra_headers = {}
        if cf_token:
            extra_headers["cf-aig-authorization"] = f"Bearer {cf_token}"
        # Provider API key for pass-through mode (optional)
        provider_key = (creds or {}).get("provider_api_key", "")
        if provider_key:
            litellm_kwargs["api_key"] = provider_key
        else:
            litellm_kwargs["api_key"] = cf_token
        if extra_headers:
            litellm_kwargs["extra_headers"] = extra_headers
    elif provider == "custom_endpoint":
        # Generic OpenAI-compatible endpoint with optional custom headers
        api_base = (creds or {}).get("api_base", "")
        if api_base:
            litellm_kwargs["api_base"] = api_base.rstrip("/")
        # Strip custom_endpoint/ prefix, route as openai-compatible
        model_name = model.split("/", 1)[1] if "/" in model else model
        litellm_kwargs["model"] = f"openai/{model_name}"
        # API key → Authorization header (optional)
        custom_api_key = (creds or {}).get("api_key", "")
        if custom_api_key:
            litellm_kwargs["api_key"] = custom_api_key
        else:
            litellm_kwargs.pop("api_key", None)
        # Custom header (optional)
        custom_header_name = (creds or {}).get("custom_header_name", "")
        custom_header_value = (creds or {}).get("custom_header_value", "")
        if custom_header_name and custom_header_value:
            litellm_kwargs["extra_headers"] = {custom_header_name: custom_header_value}

    try:
        if is_streaming:
            return await _litellm_streaming(litellm_kwargs, model)
        else:
            return await _litellm_sync(litellm_kwargs, model)
    except litellm.exceptions.AuthenticationError as e:
        logger.error(f"LiteLLM auth error: {e}")
        error = openai_error_to_anthropic(
            401, {"error": {"type": "authentication_error", "message": str(e)}}
        )
        return Response(
            content=json.dumps(error),
            status_code=401,
            media_type="application/json",
        )
    except litellm.exceptions.RateLimitError as e:
        logger.error(f"LiteLLM rate limit: {e}")
        error = openai_error_to_anthropic(
            429, {"error": {"type": "rate_limit_error", "message": str(e)}}
        )
        return Response(
            content=json.dumps(error),
            status_code=429,
            media_type="application/json",
        )
    except Exception as e:
        logger.error(f"LiteLLM error: {e}", exc_info=True)
        error = openai_error_to_anthropic(
            500, {"error": {"type": "server_error", "message": str(e)}}
        )
        return Response(
            content=json.dumps(error),
            status_code=500,
            media_type="application/json",
        )


async def _litellm_streaming(kwargs: dict, model_name: str) -> StreamingResponse:
    """Call LiteLLM with streaming, translate chunks to Anthropic SSE."""

    async def event_generator() -> AsyncIterator[str]:
        translator = StreamTranslator(model_name=model_name)

        response = await litellm.acompletion(**kwargs)

        async for chunk in response:
            for sse_event in translator.translate_chunk(chunk):
                yield sse_event

        # Finalize (close blocks, emit message_stop)
        for sse_event in translator.finalize():
            yield sse_event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _litellm_sync(kwargs: dict, model_name: str) -> Response:
    """Call LiteLLM without streaming, translate full response."""
    response = await litellm.acompletion(**kwargs)

    # Convert litellm ModelResponse to dict
    if hasattr(response, "model_dump"):
        response_dict = response.model_dump()
    else:
        response_dict = dict(response)

    # Translate to Anthropic format
    anthropic_response = openai_to_anthropic_response(response_dict, model_name)

    return Response(
        content=json.dumps(anthropic_response),
        status_code=200,
        media_type="application/json",
    )
