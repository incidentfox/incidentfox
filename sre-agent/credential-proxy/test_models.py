#!/usr/bin/env python3
"""Test script to verify LLM proxy works with multiple providers.

Tests three routing paths:
1. Claude: direct pass-through to Anthropic API
2. Direct providers: OpenAI, Gemini, DeepSeek, Kimi, MiniMax, Grok, Mistral
3. Via OpenRouter: Qwen, Cohere, and any model without a direct API key

Supports two modes:
- Direct: Test against credential-resolver on port 8002 (needs env vars loaded)
- Proxy:  Test through envoy on port 8001 (docker-compose E2E, no env vars needed)

Usage:
    # Direct mode (default) — run against credential-resolver
    set -a && source .env && set +a
    .venv/bin/uvicorn credential_resolver.main:app --port 8002
    .venv/bin/python test_models.py [filter...]

    # Proxy mode — run through docker-compose (envoy → credential-resolver → upstream)
    docker compose up -d
    .venv/bin/python test_models.py --proxy [filter...]
    # or: .venv/bin/python test_models.py --url http://localhost:8001 [filter...]
"""

import argparse
import json
import sys
import time

import httpx

# Model definitions grouped by routing path
MODELS = {
    # === Direct to official API (pass-through) ===
    "claude (direct)": "claude-sonnet-4-20250514",
    # === Direct to official API (via LiteLLM) ===
    "openai (direct)": "openai/gpt-4o-mini",
    "gemini (direct)": "gemini/gemini-2.5-flash",
    "deepseek (direct)": "deepseek/deepseek-chat",
    "kimi (direct)": "moonshot/kimi-k2-turbo-preview",
    "minimax (direct)": "minimax/MiniMax-Text-01",
    "grok (direct)": "xai/grok-3-mini",
    "mistral (direct)": "mistral/mistral-small-latest",
    # === Cloud platforms ===
    "bedrock (aws)": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "deepseek (azure ai)": "azure_ai/DeepSeek-V3.2-Speciale",
    # === Via OpenRouter (models without direct API keys) ===
    "qwen (openrouter)": "openrouter/qwen/qwen-2.5-72b-instruct",
    "cohere (openrouter)": "openrouter/cohere/command-a",
}

# Anthropic Messages API format request body
REQUEST_BODY = {
    "model": "claude-sonnet-4-20250514",  # SDK default (overridden by x-llm-model header)
    "max_tokens": 1024,
    "messages": [
        {
            "role": "user",
            "content": "Say 'Hello from <your model name>!' in exactly one sentence.",
        }
    ],
}


def test_model(
    name: str, model_id: str, base_url: str, proxy_mode: bool
) -> tuple[bool, str]:
    """Test a single model via the LLM proxy (non-streaming).

    Args:
        proxy_mode: If True, auth is handled by envoy ext_authz (no manual API key needed).
                    If False, Claude needs x-api-key from env var.
    """
    is_claude = model_id.startswith("claude")
    try:
        with httpx.Client(timeout=60.0) as client:
            headers = {
                "Content-Type": "application/json",
            }
            if is_claude and not proxy_mode:
                # Direct mode: Claude pass-through needs x-api-key
                import os

                headers["x-api-key"] = os.getenv("ANTHROPIC_API_KEY", "")
            elif not is_claude:
                headers["x-llm-model"] = model_id

            response = client.post(
                f"{base_url}/v1/messages",
                headers=headers,
                json=REQUEST_BODY,
            )

            if response.status_code != 200:
                return False, f"HTTP {response.status_code}: {response.text[:200]}"

            data = response.json()

            # Check for Anthropic error format
            if data.get("type") == "error":
                err = data.get("error", {})
                return False, f"{err.get('type')}: {err.get('message', '')[:200]}"

            # Extract text from Anthropic response format
            content = data.get("content", [])
            text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            text = " ".join(text_parts).strip()

            if not text:
                return False, f"Empty response. Full: {json.dumps(data)[:200]}"

            return True, text[:150]

    except httpx.TimeoutException:
        return False, "TIMEOUT (60s)"
    except Exception as e:
        return False, f"ERROR: {e}"


def test_model_streaming(
    name: str, model_id: str, base_url: str, proxy_mode: bool
) -> tuple[bool, str]:
    """Test a single model with streaming via the LLM proxy."""
    is_claude = model_id.startswith("claude")
    body = {**REQUEST_BODY, "stream": True}
    try:
        with httpx.Client(timeout=60.0) as client:
            headers = {
                "Content-Type": "application/json",
            }
            if is_claude and not proxy_mode:
                import os

                headers["x-api-key"] = os.getenv("ANTHROPIC_API_KEY", "")
            elif not is_claude:
                headers["x-llm-model"] = model_id

            with client.stream(
                "POST",
                f"{base_url}/v1/messages",
                headers=headers,
                json=body,
            ) as response:
                if response.status_code != 200:
                    error_body = response.read().decode()
                    return False, f"HTTP {response.status_code}: {error_body[:200]}"

                text_chunks = []
                event_types = set()
                for line in response.iter_lines():
                    if line.startswith("event: "):
                        event_types.add(line[7:])
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "content_block_delta":
                                delta = data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text_chunks.append(delta.get("text", ""))
                        except json.JSONDecodeError:
                            pass

                text = "".join(text_chunks).strip()
                events = ", ".join(sorted(event_types))

                if not text:
                    return False, f"No text in stream. Events: {events}"

                return True, f"{text[:120]} [events: {events}]"

    except httpx.TimeoutException:
        return False, "TIMEOUT (60s)"
    except Exception as e:
        return False, f"ERROR: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Test LLM proxy with multiple providers"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Base URL (default: http://localhost:8002, or :8001 with --proxy)",
    )
    parser.add_argument(
        "--proxy",
        action="store_true",
        help="Proxy mode: test through envoy (port 8001). Auth handled by ext_authz.",
    )
    parser.add_argument(
        "filters",
        nargs="*",
        help="Filter models by name (e.g., 'openai', 'claude bedrock')",
    )
    args = parser.parse_args()

    if args.url:
        base_url = args.url.rstrip("/")
    elif args.proxy:
        base_url = "http://localhost:8001"
    else:
        base_url = "http://localhost:8002"

    proxy_mode = args.proxy or ":8001" in base_url

    # Check server is running
    health_url = base_url
    # In proxy mode, health check goes to envoy admin or credential-resolver directly
    if proxy_mode:
        health_url = "http://localhost:8002"  # Check credential-resolver directly
    try:
        r = httpx.get(f"{health_url}/health", timeout=5.0)
        print(f"Server health: {r.json()}")
    except Exception:
        print(f"ERROR: Server not running at {health_url}")
        if proxy_mode:
            print("Start docker-compose:")
            print("  docker compose up -d")
        else:
            print("Start credential-resolver:")
            print("  set -a && source .env && set +a")
            print("  .venv/bin/uvicorn credential_resolver.main:app --port 8002")
        sys.exit(1)

    mode_label = f"PROXY ({base_url})" if proxy_mode else f"DIRECT ({base_url})"
    print(f"Mode: {mode_label}\n")

    # Filter models if args provided
    models = MODELS
    if args.filters:
        filter_names = [f.lower() for f in args.filters]
        models = {
            k: v for k, v in MODELS.items() if any(f in k.lower() for f in filter_names)
        }
        if not models:
            print(f"No models match filter: {args.filters}")
            print(f"Available: {list(MODELS.keys())}")
            sys.exit(1)

    print(f"Testing {len(models)} models (non-streaming)...\n")
    print("-" * 80)

    results = {}
    for name, model_id in models.items():
        print(f"  {name:30s} ({model_id})")
        start = time.time()
        ok, msg = test_model(name, model_id, base_url, proxy_mode)
        elapsed = time.time() - start
        status = "PASS" if ok else "FAIL"
        results[name] = ok
        print(f"  {'':30s} [{status}] ({elapsed:.1f}s) {msg}")
        print()

    print("-" * 80)
    print(f"\nTesting {len(models)} models (streaming)...\n")
    print("-" * 80)

    stream_results = {}
    for name, model_id in models.items():
        print(f"  {name:30s} ({model_id})")
        start = time.time()
        ok, msg = test_model_streaming(name, model_id, base_url, proxy_mode)
        elapsed = time.time() - start
        status = "PASS" if ok else "FAIL"
        stream_results[name] = ok
        print(f"  {'':30s} [{status}] ({elapsed:.1f}s) {msg}")
        print()

    print("-" * 80)
    print("\n=== SUMMARY ===\n")
    for name in models:
        sync_ok = results.get(name, False)
        stream_ok = stream_results.get(name, False)
        sync_icon = "OK" if sync_ok else "FAIL"
        stream_icon = "OK" if stream_ok else "FAIL"
        print(f"  {name:30s}  sync={sync_icon:4s}  stream={stream_icon:4s}")

    total_pass = sum(1 for v in results.values() if v) + sum(
        1 for v in stream_results.values() if v
    )
    total = len(results) + len(stream_results)
    print(f"\n  Total: {total_pass}/{total} passed")

    # Exit with non-zero if any test failed
    if total_pass < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
