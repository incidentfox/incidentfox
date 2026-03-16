---
description: "Bootstrap observability setup — add logging, metrics, and tracing to a project from scratch"
---

# Observability Bootstrap

Set up structured logging, metrics, and tracing from scratch for this project.

## Instructions

The user wants to bootstrap observability for: **$ARGUMENTS**

If no arguments, detect the project type and suggest the best stack.

## Step 1: Detect Project

Analyze the project to determine:
- **Language/Runtime**: Node.js, Python, Go, Java, etc.
- **Framework**: Next.js, Express, FastAPI, Django, Gin, Spring Boot, etc.
- **Deployment**: Vercel, AWS, GCP, Docker, Kubernetes, etc.
- **Existing observability**: Any logging/metrics/tracing already present?

## Step 2: Recommend Stack

Based on the project, recommend:

### Node.js / TypeScript
- **Logging**: `pino` (fast structured JSON logging)
- **Metrics**: `prom-client` (Prometheus) or Datadog via `dd-trace`
- **Tracing**: `@opentelemetry/sdk-node` (vendor-neutral)
- **Correlation**: Request ID middleware

### Python
- **Logging**: `structlog` (structured, context-aware)
- **Metrics**: `prometheus_client` or Datadog `ddtrace`
- **Tracing**: `opentelemetry-sdk`
- **Correlation**: Context vars middleware

### Go
- **Logging**: `log/slog` (stdlib structured logging)
- **Metrics**: `prometheus/client_golang`
- **Tracing**: `go.opentelemetry.io/otel`
- **Correlation**: Context-based middleware

### Next.js on Vercel (Nick's stack)
- **Logging**: `pino` + Vercel Log Drains (to Datadog/Axiom/Betterstack)
- **Metrics**: Vercel Analytics + custom via `@vercel/otel`
- **Tracing**: `@vercel/otel` (OpenTelemetry, built-in support)
- **Correlation**: Next.js middleware for request IDs

## Step 3: Generate Bootstrap Code

Generate the minimal setup files:

1. **Logger utility** — configured structured logger with standard fields
2. **Request context middleware** — injects request ID, user ID, correlation ID
3. **Error handler wrapper** — catches unhandled errors with full context
4. **Example usage** — one example endpoint with proper observability

The bootstrap should be:
- Copy-paste ready
- Match the project's existing style
- Minimal — just enough to start, not a framework
- Well-commented explaining WHY each piece matters

## Step 4: Checklist

```
## Observability Bootstrap Complete

### Installed:
- [ ] Structured logging library
- [ ] Request ID middleware
- [ ] Error handling with context
- [ ] Example instrumented endpoint

### Next steps:
- [ ] Run /observability-coverage:review to find gaps in existing code
- [ ] Set up log drain to your observability platform
- [ ] Add metrics endpoint for Prometheus scraping (if applicable)
- [ ] Configure distributed tracing exporter

### Recommended observability platforms for startups:
- **Free tier**: Grafana Cloud, Axiom, Betterstack
- **Paid but worth it**: Datadog, Honeycomb
- **Self-hosted**: Grafana + Loki + Tempo + Prometheus
```
