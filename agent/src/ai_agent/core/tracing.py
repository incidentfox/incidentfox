"""
Tracing abstraction layer with Langfuse for LLM observability.

Uses OpenInference instrumentation for OpenAI Agents SDK as per:
https://langfuse.com/integrations/frameworks/openai-agents

This module provides:
1. Auto-instrumentation of OpenAI Agents SDK (LLM calls, tool usage, handoffs)
2. Manual trace/span creation for additional context
3. OTEL fallback for general distributed tracing

Configuration:
    LANGFUSE_PUBLIC_KEY: Langfuse public key
    LANGFUSE_SECRET_KEY: Langfuse secret key
    LANGFUSE_HOST: Langfuse host (default: https://us.cloud.langfuse.com)
    TRACING_ENABLED: Enable/disable tracing (default: true)

Usage:
    # At startup, call setup_openai_agents_tracing():
    from ai_agent.core.tracing import setup_openai_agents_tracing
    setup_openai_agents_tracing()

    # Agent runs are auto-instrumented. For grouping multiple runs:
    from agents import trace
    with trace("My workflow"):
        result = await Runner.run(agent, "...")
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, TypeVar

# Lazy imports to avoid hard dependencies
_langfuse_client: Any = None
_otel_tracer: Any = None

# Context vars for trace propagation
_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_current_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)

T = TypeVar("T")


class TracingConfig:
    """Tracing configuration loaded from environment."""

    def __init__(self) -> None:
        self.enabled = os.getenv("TRACING_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        self.sample_rate = float(os.getenv("TRACING_SAMPLE_RATE", "1.0"))

        # OTEL config
        self.otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

        # Langfuse config
        self.langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        self.langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        self.langfuse_host = os.getenv(
            "LANGFUSE_HOST", "https://us.cloud.langfuse.com"
        ).strip()

        # Service identification
        self.service_name = os.getenv("OTEL_SERVICE_NAME", "incidentfox-agent")
        self.service_version = os.getenv("OTEL_SERVICE_VERSION", "1.0.0")

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def otlp_enabled(self) -> bool:
        return bool(self.otlp_endpoint)


_config: TracingConfig | None = None


def get_tracing_config() -> TracingConfig:
    """Get or create tracing configuration."""
    global _config
    if _config is None:
        _config = TracingConfig()
    return _config


def _init_langfuse() -> Any:
    """Initialize Langfuse client if configured."""
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    config = get_tracing_config()
    if not config.langfuse_enabled:
        return None

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_host,
        )
        return _langfuse_client
    except ImportError:
        return None
    except Exception as e:
        logger.warning("langfuse_initialization_failed", error=str(e))
        return None


_agents_instrumented: bool = False


def setup_openai_agents_tracing() -> bool:
    """
    Set up Langfuse tracing for OpenAI Agents SDK.

    This initializes the Langfuse client for manual tracing.
    Note: OpenInference auto-instrumentation is disabled due to conflicts
    with Langfuse's OpenAI wrapper. Manual tracing is used instead.

    Call this once at application startup before running any agents.

    Returns:
        True if Langfuse was initialized, False otherwise.
    """
    global _agents_instrumented

    if _agents_instrumented:
        return True

    config = get_tracing_config()
    if not config.enabled or not config.langfuse_enabled:
        logger.info("langfuse_tracing_disabled")
        return False

    try:
        from langfuse import Langfuse

        # Just initialize Langfuse client - don't use OpenInference
        # because it conflicts with Langfuse's OpenAI wrapper
        langfuse = Langfuse(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_host,
        )
        if langfuse.auth_check():
            logger.info("langfuse_tracing_initialized", mode="manual")
            _agents_instrumented = True
            return True
        else:
            logger.warning("langfuse_auth_check_failed")
            return False

    except ImportError as e:
        logger.warning("langfuse_initialization_error", error=str(e))
        return False
    except Exception as e:
        logger.warning("langfuse_init_failed", error=str(e))
        return False


def _init_otel_tracer() -> Any:
    """Initialize OpenTelemetry tracer if configured."""
    global _otel_tracer
    if _otel_tracer is not None:
        return _otel_tracer

    config = get_tracing_config()

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(
            attributes={
                SERVICE_NAME: config.service_name,
                SERVICE_VERSION: config.service_version,
            }
        )

        provider = TracerProvider(resource=resource)

        # Add OTLP exporter if configured
        if config.otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        trace.set_tracer_provider(provider)
        _otel_tracer = trace.get_tracer(config.service_name, config.service_version)
        return _otel_tracer
    except ImportError:
        return None
    except Exception as e:
        logger.warning("otel_tracer_init_failed", error=str(e))
        return None


def get_tracer() -> Any:
    """Get the configured tracer (OTEL or Langfuse wrapper)."""
    config = get_tracing_config()
    if not config.enabled:
        return None

    # Prefer Langfuse for LLM-specific tracing
    langfuse = _init_langfuse()
    if langfuse:
        return langfuse

    # Fall back to OTEL
    return _init_otel_tracer()


class NoOpSpan:
    """No-op span for when tracing is disabled."""

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def end(self) -> None:
        pass


@contextmanager
def trace_agent_run(
    agent_name: str,
    correlation_id: str,
    user_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """
    Context manager for tracing an agent run.

    When OpenInference instrumentation is enabled, this adds additional
    context to the auto-generated traces. Otherwise, it creates a manual
    Langfuse trace or OTEL span.

    Args:
        agent_name: Name of the agent being run
        correlation_id: Unique ID for this run (used for log correlation)
        user_message: The user's input message
        metadata: Additional metadata to attach
    """
    config = get_tracing_config()
    if not config.enabled:
        yield NoOpSpan()
        return

    start_time = time.time()
    _current_trace_id.set(correlation_id)

    # Note: OpenInference auto-instrumentation is disabled due to conflicts
    # with Langfuse's OpenAI wrapper. Using manual Langfuse tracing instead.

    # Fallback to manual Langfuse tracing
    langfuse = _init_langfuse()
    if langfuse:
        try:
            trace = langfuse.trace(
                id=correlation_id,
                name=f"agent_run:{agent_name}",
                input={"message": user_message} if user_message else None,
                metadata={
                    "agent_name": agent_name,
                    "service": config.service_name,
                    **(metadata or {}),
                },
            )
            try:
                yield NoOpSpan()
                trace.update(
                    output={"status": "success"},
                    metadata={
                        **(metadata or {}),
                        "duration_seconds": time.time() - start_time,
                    },
                )
            except Exception as e:
                trace.update(
                    output={"status": "error", "error": str(e)},
                    metadata={
                        **(metadata or {}),
                        "duration_seconds": time.time() - start_time,
                        "error_type": type(e).__name__,
                    },
                )
                raise
            return
        except Exception as e:
            logger.warning("langfuse_tracing_failed", error=str(e))

    # Fall back to OTEL
    tracer = _init_otel_tracer()
    if tracer:

        with tracer.start_as_current_span(
            f"agent_run:{agent_name}",
            attributes={
                "agent.name": agent_name,
                "agent.correlation_id": correlation_id,
                "agent.input": user_message[:500] if user_message else "",
                **({"agent." + k: str(v) for k, v in (metadata or {}).items()}),
            },
        ) as span:
            try:
                yield span
                span.set_attribute("agent.status", "success")
                span.set_attribute("agent.duration_seconds", time.time() - start_time)
            except Exception as e:
                span.set_attribute("agent.status", "error")
                span.set_attribute("agent.error", str(e))
                span.record_exception(e)
                raise
        return

    # No tracing available
    yield NoOpSpan()


@contextmanager
def trace_tool_call(
    tool_name: str,
    **kwargs: Any,
) -> Generator[Any, None, None]:
    """
    Trace a tool call within an agent run.

    Args:
        tool_name: Name of the tool being called
        **kwargs: Tool parameters to record
    """
    config = get_tracing_config()
    if not config.enabled:
        yield NoOpSpan()
        return

    start_time = time.time()
    trace_id = _current_trace_id.get()

    # Try Langfuse first
    langfuse = _init_langfuse()
    if langfuse and trace_id:
        try:
            # Create a span within the current trace
            span = langfuse.span(
                trace_id=trace_id,
                name=f"tool:{tool_name}",
                input=kwargs if kwargs else None,
            )
            try:
                yield span
                span.end(output={"status": "success"})
            except Exception as e:
                span.end(
                    output={"status": "error", "error": str(e)},
                    level="ERROR",
                )
                raise
            return
        except Exception as e:
            logger.warning("langfuse_tool_tracing_failed", error=str(e))

    # Fall back to OTEL
    tracer = _init_otel_tracer()
    if tracer:
        with tracer.start_as_current_span(
            f"tool:{tool_name}",
            attributes={
                "tool.name": tool_name,
                **{f"tool.param.{k}": str(v)[:200] for k, v in kwargs.items()},
            },
        ) as span:
            try:
                yield span
                span.set_attribute("tool.status", "success")
                span.set_attribute("tool.duration_seconds", time.time() - start_time)
            except Exception as e:
                span.set_attribute("tool.status", "error")
                span.record_exception(e)
                raise
        return

    yield NoOpSpan()


@contextmanager
def trace_llm_call(
    model: str,
    prompt: str | None = None,
    **kwargs: Any,
) -> Generator[Any, None, None]:
    """
    Trace an LLM call (for Langfuse generation tracking).

    Args:
        model: Model name (e.g., "gpt-5.2")
        prompt: The prompt sent to the model
        **kwargs: Additional parameters
    """
    config = get_tracing_config()
    if not config.enabled:
        yield NoOpSpan()
        return

    start_time = time.time()
    trace_id = _current_trace_id.get()

    # Langfuse has first-class LLM generation support
    langfuse = _init_langfuse()
    if langfuse and trace_id:
        try:
            generation = langfuse.generation(
                trace_id=trace_id,
                name=f"llm:{model}",
                model=model,
                input=prompt[:1000] if prompt else None,
                model_parameters=kwargs,
            )
            try:
                yield generation
            except Exception as e:
                generation.end(
                    output={"error": str(e)},
                    level="ERROR",
                )
                raise
            return
        except Exception as e:
            logger.warning("langfuse_llm_tracing_failed", error=str(e))

    # Fall back to OTEL span
    tracer = _init_otel_tracer()
    if tracer:
        with tracer.start_as_current_span(
            f"llm:{model}",
            attributes={
                "llm.model": model,
                "llm.prompt_length": len(prompt) if prompt else 0,
                **{f"llm.{k}": str(v) for k, v in kwargs.items()},
            },
        ) as span:
            yield span
        return

    yield NoOpSpan()


def trace_decorator(
    span_name: str | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to trace a function.

    Args:
        span_name: Optional span name (defaults to function name)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            name = span_name or func.__name__
            with trace_tool_call(
                name,
                **{
                    k: v
                    for k, v in kwargs.items()
                    if isinstance(v, (str, int, float, bool))
                },
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def flush_traces() -> None:
    """Flush any pending traces to backends."""
    langfuse = _init_langfuse()
    if langfuse:
        try:
            langfuse.flush()
        except Exception:
            pass
