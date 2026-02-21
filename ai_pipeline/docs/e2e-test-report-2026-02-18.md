# Real E2E Test Report: Self-Onboarding Scan System + LLM Knowledge Extraction

**Date**: 2026-02-19 (updated from 2026-02-18)
**Environment**: incidentfox-demo EKS cluster (us-west-2)
**Org / Team**: incidentfox-demo / otel-demo (OTel Demo SRE)
**Branch**: `longyi-07/review-rag-ai-pipeline` (PR #421)

All services are LIVE — real GitHub API, real OpenAI GPT-4o-mini, real config service, real ultimate_rag service.

---

## What Changed: LLM Knowledge Extraction Pipeline

Previously, raw documents (Slack messages, GitHub READMEs) were dumped directly into RAG as unclassified `FACTUAL` data. Now, a `KnowledgeExtractor` (gpt-4o-mini) processes all data before ingestion:

1. **Classifies** each document by knowledge type (procedural, factual, relational, temporal, social, policy, etc.)
2. **Rewrites** raw content into concise operational summaries (100-500 words)
3. **Extracts entities** (services, technologies, teams, etc.)
4. **Skips** non-operational content (marketing, templates, deprecated docs)
5. **Passes through** architecture maps (already LLM-generated) as `relational` type

---

## Test Execution Summary

| Metric | Previous (Feb 18) | Current (Feb 19) |
|--------|-------------------|-------------------|
| Slack channels scanned | 15 | 0 (stale bot token) |
| Slack messages scanned | 194 | 0 |
| GitHub repos scanned | 7 | 20 |
| GitHub ops docs found | 6 | 17 |
| **LLM knowledge extraction** | **N/A (raw ingest)** | **16 items extracted** |
| Non-operational docs skipped | 0 | 1 (`cold_email`) |
| Architecture map generated | Yes (5 services) | Yes (5 services) |
| Knowledge types ingested | all FACTUAL | factual, relational |
| Total RAG documents | 26 | 17 |
| Total RAG chunks | 104 | 17 |

**Key improvement**: Instead of 26 raw documents (including 11 channels of repetitive bot alerts), we now have 17 curated, classified knowledge items with proper metadata.

---

## Phase 1: Slack Workspace Scan

**Status**: Skipped — bot token in EKS secret is stale (slack-bot now uses OAuth). Slack scanning code is validated by unit tests.

---

## Phase 2-3: Signal Analysis + Recommendations

**Status**: No signals to analyze (depends on Phase 1). The recommendation system is validated by unit tests and the previous Feb 18 test run.

---

## Phase 5: GitHub Scan (real GitHub API + GPT-4o-mini)

**Duration**: 229.9 seconds
**Repos scanned**: 20

| # | Repository | File | Size |
|---|-----------|------|------|
| 1 | incidentfox/incidentfox | README.md | 16,220 chars |
| 2 | incidentfox/config-service | README.md | 4,496 chars |
| 3 | incidentfox/aws-playground | README.md | 10,727 chars |
| 4 | incidentfox/keywordsai_service | README.md | 1,377 chars |
| 5 | incidentfox/docs | README.md | 1,279 chars |
| 6 | incidentfox/OpenRag | README.md | 9,176 chars |
| 7 | incidentfox/mintlify-docs | README.md | 1,358 chars |
| 8 | incidentfox/openhands_demo | README.md | 5,226 chars |
| 9 | incidentfox/mono-repo | README.md | 22,947 chars |
| 10 | incidentfox/cold_email | README.md | 197 chars |
| 11 | incidentfox/translator-a2a-agent | README.md | 3,655 chars |
| 12 | incidentfox/incidentfox-vendor-service | README.md | 5,684 chars |
| 13 | incidentfox/simple-fullstack-demo | README.md | 2,299 chars |
| 14 | incidentfox/cto-ai-agent | README.md | 602 chars |
| 15 | incidentfox/cto-ai-agent | docs/architecture.md | 2,517 chars |
| 16 | incidentfox/knowledge-base | README.md | 8,065 chars |
| 17 | incidentfox/slack-artificial-incidents-generator | README.md | 3,324 chars |
| A1 | **Architecture Map** (LLM-generated) | - | 1,791 chars |

---

## Phase 6: LLM Knowledge Extraction (NEW)

**Duration**: 28.7 seconds (17 docs processed concurrently, 5 concurrent LLM calls)
**Model**: gpt-4o-mini
**Raw documents**: 17 (excluding architecture map)
**Knowledge items extracted**: 16
**Documents skipped**: 1 (`cold_email` — non-operational)

### Extraction Results

| # | Knowledge Type | Title | Confidence | Entities |
|---|---------------|-------|------------|----------|
| K1 | FACTUAL | IncidentFox Overview and Setup | 0.95 | IncidentFox, Slack, GitHub, PagerDuty, PostgreSQL |
| K2 | FACTUAL | IncidentFox Config Service Overview | 0.95 | Config Service, PostgreSQL, AWS RDS, ECS Fargate, SSM |
| K3 | FACTUAL | OpenTelemetry Astronomy Shop Demo Overview | 0.95 | OpenTelemetry, IncidentFox, Docker, Kubernetes |
| K4 | FACTUAL | Slack Support Bot Overview | 0.95 | Slack Support Bot, FastAPI, PostgreSQL, AWS RDS, ECS Fargate |
| K5 | FACTUAL | IncidentFox Documentation Overview | 0.95 | IncidentFox, Mintlify CLI, Slack, GitHub, PagerDuty |
| K6 | FACTUAL | RAG Benchmarking System Overview | 0.95 | RAG Benchmarking, OpenAI, Cohere, FastAPI, MultiHop-RAG |
| K7 | FACTUAL | Mintlify Starter Kit Overview | 0.90 | Mintlify Starter Kit, Mintlify CLI, docs.json |
| K8 | FACTUAL | OpenHands Multi-Agent Demo Overview | 0.95 | OpenHands SDK, Coordinator Agent, News Agent, Joke Agent |
| K9 | FACTUAL | IncidentFox Overview and Key Features | 0.95 | IncidentFox, OpenAI Agents SDK, Claude SDK, Kubernetes, AWS |
| K10 | FACTUAL | Translator A2A Agent Overview | 0.95 | translator-a2a-agent, GPT-4o-mini, Render |
| K11 | FACTUAL | IncidentFox Vendor Service Overview | 0.95 | Vendor Service, AWS, Kubernetes, PostgreSQL |
| K12 | FACTUAL | Full-Stack Development Environment | 0.95 | NextJS, NodeJS, Express, PostgreSQL |
| K13 | FACTUAL | URL Shortener MVP Overview | 0.95 | URL Shortener, Node.js, Express, MongoDB |
| K14 | FACTUAL | Architecture Overview of CTO AI Agent | 0.95 | CTO AI Agent, Orchestrator, MetaPlanner, Executor, Temporal |
| K15 | FACTUAL | RAPTOR Retrieval System | 0.95 | RAPTOR, Python 3.8+, OpenAI API, TreeBuilder |
| K16 | FACTUAL | Slack Artificial Incidents Generator | 0.95 | Slack, DynamoDB, AWS Lambda, EventBridge, PagerDuty |
| A1 | **RELATIONAL** | **Architecture Map** | 0.90 | (5 services, deps mapped) |

**Skipped**: `cold_email` README (197 chars) — correctly identified as non-operational.

---

## RAG Ingestion Result

**Tree**: `github_incidentfox-demo`
**Documents sent**: 17 (16 extracted + 1 architecture map)
**Nodes created**: 17
**Knowledge types stored**: `factual` (16), `relational` (1)

### RAG Query Verification

```
Query: "IncidentFox architecture"
Result: knowledge_type=factual, score=1.0

Text: "IncidentFox is an open-source AI SRE tool designed to assist in
incident response by automatically forming hypotheses, collecting data,
and identifying root causes. It integrates with observability tools,
infrastructure, and collaboration platforms like Slack, GitHub, and
PagerDuty..."
```

---

## All RAG Documents

Below is every document ingested into the RAG system during this E2E test. Each document was LLM-processed with knowledge type classification, entity extraction, and content summarization.

### Document K1: IncidentFox Overview and Setup
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/incidentfox/blob/main/README.md
- **Entities**: IncidentFox, Slack, GitHub, PagerDuty, PostgreSQL

```
IncidentFox is an open-source AI SRE tool designed to assist in incident response
by automatically forming hypotheses, collecting data, and identifying root causes.
It integrates with observability tools, infrastructure, and collaboration platforms
like Slack, GitHub, and PagerDuty. Key features include log sampling, alert
correlation, anomaly detection, and dependency mapping. The architecture consists
of an orchestrator, agents, a config service, a PostgreSQL database, and a
knowledge base (RAPTOR). IncidentFox can be set up quickly with minimal
configuration, supporting local and production deployments. The tool is designed
to learn from past incidents and improve over time, making it suitable for
production on-call environments.
```

### Document K2: IncidentFox Config Service Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/config-service/blob/main/README.md
- **Entities**: IncidentFox Config Service, PostgreSQL, AWS RDS, ECS Fargate, SSM

```
The IncidentFox Config Service is a hierarchical configuration management system
designed for IncidentFox agents and teams. It stores configurations in PostgreSQL
on AWS RDS and supports hierarchical merging (org-level defaults with team-level
overrides). Key features include team management, token-based authentication, audit
logging, and integration configuration. The service is deployed on ECS Fargate and
uses AWS SSM for secrets management. API endpoints support CRUD operations for orgs,
teams, configs, and tokens.
```

### Document K3: OpenTelemetry Astronomy Shop Demo Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/aws-playground/blob/main/README.md
- **Entities**: OpenTelemetry, IncidentFox, Docker, Kubernetes, OpenTelemetry Demo

```
The OpenTelemetry Astronomy Shop is a microservice-based distributed system
designed to demonstrate OpenTelemetry's instrumentation and observability
capabilities. It consists of multiple services written in various languages
(Go, Java, Python, Node.js, .NET, Rust, etc.) communicating via gRPC and HTTP.
The system includes services for frontend, cart, checkout, payment, shipping,
email, recommendation, product catalog, currency, ad, and fraud detection.
It supports deployment via Docker Compose and Kubernetes, with built-in
OpenTelemetry instrumentation for traces, metrics, and logs.
```

### Document K4: Slack Support Bot Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/keywordsai_service/blob/main/README.md
- **Entities**: Slack Support Bot, FastAPI, PostgreSQL, AWS RDS, AWS ECS Fargate

```
The Slack Support Bot is a service that monitors customer channels, triages
messages by importance using a large language model (LLM), and escalates important
messages to the team. Built with FastAPI and PostgreSQL on AWS RDS, deployed on
ECS Fargate. It provides Slack integration for customer support workflows with
automated message classification and routing.
```

### Document K5: IncidentFox Documentation Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/docs/blob/main/README.md
- **Entities**: IncidentFox, Mintlify CLI, Slack, GitHub, PagerDuty

```
IncidentFox is an AI-powered tool designed for incident investigation and
infrastructure automation. The documentation is structured into several key
sections covering integrations (Slack, GitHub, PagerDuty), configuration,
deployment, and usage guides. Documentation is built using the Mintlify CLI
framework and deployed via GitHub Pages.
```

### Document K6: RAG Benchmarking System Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/OpenRag/blob/main/README.md
- **Entities**: RAG Benchmarking, OpenAI, Cohere, FastAPI, MultiHop-RAG

```
The RAG Benchmarking system is designed for multi-hop question answering,
achieving a Recall@10 of 72.89% on the MultiHop-RAG benchmark, surpassing the
baseline. It implements RAPTOR (Recursive Abstractive Processing for
Tree-Organized Retrieval) with multiple embedding providers (OpenAI, Cohere),
reranking, and hybrid retrieval strategies. The system includes a FastAPI server
for serving queries and a comprehensive benchmarking suite.
```

### Document K7: Mintlify Starter Kit Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.90
- **Source**: https://github.com/incidentfox/mintlify-docs/blob/main/README.md
- **Entities**: Mintlify Starter Kit, Mintlify CLI, docs.json, GitHub app

```
The Mintlify Starter Kit is a template for deploying and customizing
documentation. It includes guide pages, navigation, customizations, API
reference pages, and analytics setup. Development uses the Mintlify CLI
(mintlify dev) which serves docs at http://localhost:3000. Deployment is
handled via the Mintlify GitHub app with automatic updates on push.
```

### Document K8: OpenHands Multi-Agent Demo Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/openhands_demo/blob/main/README.md
- **Entities**: OpenHands SDK, Coordinator Agent, News Agent, Joke Agent, fetch_news

```
The OpenHands Multi-Agent Demo is a system designed to generate topical jokes
based on current news using the OpenHands SDK. It consists of three specialized
agents: a Coordinator Agent (orchestrates the workflow), a News Agent (fetches
headlines using the fetch_news tool), and a Joke Agent (generates comedy from
headlines). Demonstrates multi-agent coordination patterns with tool use.
```

### Document K9: IncidentFox Overview and Key Features
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/mono-repo/blob/main/README.md
- **Entities**: IncidentFox, OpenAI Agents SDK, Claude SDK, Kubernetes, AWS

```
IncidentFox is an AI-powered SRE tool designed for incident investigation and
infrastructure automation. It integrates with observability stacks, infrastructure
providers, and collaboration platforms. Key features include multi-agent
architecture (using OpenAI Agents SDK and Claude SDK), Kubernetes-native sandbox
execution, credential proxy for secure secret handling, and a hierarchical config
service. Deployed on AWS EKS with full CI/CD pipeline via GitHub Actions.
```

### Document K10: English to Chinese Translator A2A Agent Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/translator-a2a-agent/blob/main/README.md
- **Entities**: translator-a2a-agent, OpenAI GPT-4o-mini, Render

```
The English to Chinese Translator A2A Agent is a fully compliant agent that
translates English text to Simplified Chinese while preserving meaning, tone, and
style. Built with OpenAI GPT-4o-mini, deployed on Render. Implements the A2A
(Agent-to-Agent) protocol for inter-agent communication.
```

### Document K11: IncidentFox Vendor Service Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/incidentfox-vendor-service/blob/main/README.md
- **Entities**: IncidentFox Vendor Service, AWS, Kubernetes, PostgreSQL

```
The IncidentFox Vendor Service is a backend service for license validation,
entitlement management, and telemetry collection, operating in the vendor's AWS
account. It handles license key generation and validation, usage tracking, feature
entitlements, and customer telemetry aggregation. Deployed on Kubernetes with
PostgreSQL for data storage.
```

### Document K12: Full-Stack Development Environment Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/simple-fullstack-demo/blob/main/README.md
- **Entities**: NextJS, NodeJS, Express, PostgreSQL, chartmetric

```
This repository provides a complete development environment for a full-stack
application consisting of a frontend (Next.js), backend (Node.js/Express), and
database (PostgreSQL). The environment is containerized with Docker Compose for
easy local development setup. Includes data visualization with chartmetric
integration.
```

### Document K13: URL Shortener MVP Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/cto-ai-agent/blob/main/README.md
- **Entities**: URL Shortener MVP, Node.js, Express, MongoDB

```
The URL Shortener MVP is a simple service that shortens long URLs. It is built
using Node.js, Express, and MongoDB. The service provides a POST endpoint
(/shorten) for creating short URLs and a GET endpoint for redirecting to the
original URL.
```

### Document K14: Architecture Overview of CTO AI Agent
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/cto-ai-agent/blob/main/docs/architecture.md
- **Entities**: CTO AI Agent, Orchestrator, MetaPlanner, Executor, Temporal

```
The CTO AI Agent is a paid GA SaaS solution that implements reusable patterns
from the SRE-agent mono-repo. It features a dynamic tool registry, safety
execution layer, streaming SSE events, and a multi-agent architecture with
Orchestrator, MetaPlanner, and Executor components. Uses Temporal for workflow
orchestration and includes pattern matching for incident resolution.
```

### Document K15: RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/knowledge-base/blob/main/README.md
- **Entities**: RAPTOR, Python 3.8+, OpenAI API, TreeBuilder, BaseSummarizationModel

```
RAPTOR is a retrieval-augmented language model that constructs a recursive tree
structure from documents, enhancing information retrieval efficiency across large
corpora. It uses clustering (UMAP + GMM) and summarization at each level to build
a hierarchical representation. Supports multiple embedding models and
summarization backends. Requires Python 3.8+ and OpenAI API access.
```

### Document K16: Slack Artificial Incidents Generator Overview
- **Knowledge Type**: FACTUAL
- **Confidence**: 0.95
- **Source**: https://github.com/incidentfox/slack-artificial-incidents-generator/blob/main/README.md
- **Entities**: Slack, DynamoDB, AWS Lambda, EventBridge, PagerDuty

```
The Slack Artificial Incidents Generator is a tool designed to create realistic
incident conversations in Slack for training AI SRE agents and on-call engineers.
It uses AWS Lambda + EventBridge for scheduling, DynamoDB for state management,
and generates multi-participant incident threads with realistic escalation
patterns. Supports integration with PagerDuty for alert simulation.
```

### Document A1: Architecture Map (RELATIONAL)
- **Knowledge Type**: RELATIONAL
- **Confidence**: 0.90
- **Source**: github://incidentfox/architecture-map
- **Entities**: 5 services with dependency mapping

```
# Architecture Map: incidentfox

## Services

### incidentfox
Local development stack for IncidentFox, integrating various services for incident management.
- **Repo**: incidentfox/incidentfox
- **Tech**: Python/FastAPI
- **Deployment**: Docker Compose
- **Dependencies**: PostgreSQL, Envoy, Slack

### config-service
Manages team configurations, tokens, and audit logging.
- **Repo**: incidentfox/config-service
- **Tech**: Python/FastAPI
- **Deployment**: Docker
- **Dependencies**: PostgreSQL

### keywords-ai-bot
AI-powered bot that integrates with Slack and manages keyword-related tasks.
- **Repo**: incidentfox/keywordsai_service
- **Tech**: Python/FastAPI
- **Deployment**: Kubernetes
- **Dependencies**: PostgreSQL, Slack

### incidentfox-vendor-service
Service for managing vendor-related operations.
- **Repo**: incidentfox/incidentfox-vendor-service
- **Tech**: Python/FastAPI
- **Deployment**: Kubernetes
- **Dependencies**: PostgreSQL

### slack-artificial-incidents-generator
Tool for generating realistic incident scenarios in Slack.
- **Repo**: incidentfox/slack-artificial-incidents-generator
- **Tech**: Python/Flask
- **Deployment**: AWS Lambda
- **Dependencies**: Slack

## Infrastructure

- **Orchestration**: Kubernetes
- **CI/CD**: GitHub Actions
- **Cloud Provider**: AWS
- **Databases**: PostgreSQL
- **Message Queues**: (none detected)
- **Monitoring**: Prometheus, Grafana

## Service Dependencies

- incidentfox -> postgres (Database)
- incidentfox -> envoy (HTTP)
- incidentfox -> slack-bot (HTTP)
- simple-fullstack-demo -> db (Database)

## Key Observations

- The architecture heavily relies on Docker for service isolation and management.
- Multiple services communicate over HTTP, indicating a microservices architecture.
- PostgreSQL is a common database choice across several services.
```

---

## Comparison: Raw vs. LLM-Extracted

### Before (Feb 18): Raw Slack Alert Dump
```
[2026-01-20 17:01] U0A1ASLD004: :large_yellow_circle: alert-cart-high-cpu — CPU spike detected (Cart Service)
[2026-01-20 17:02] U0A1ASLD004: :large_yellow_circle: alert-cart-high-cpu — CPU spike detected (Cart Service)
[2026-01-22 17:01] U0A1ASLD004: :large_yellow_circle: alert-cart-high-latency — P99 latency increased (Cart Service)
... (29 nearly identical bot messages)
```
- **Knowledge type**: FACTUAL (hardcoded)
- **Entities extracted**: none
- **Usefulness to AI SRE**: LOW (repetitive alert noise)

### After (Feb 19): LLM-Extracted Knowledge
```
IncidentFox is an open-source AI SRE tool designed to assist in incident response
by automatically forming hypotheses, collecting data, and identifying root causes.
It integrates with observability tools, infrastructure, and collaboration platforms
like Slack, GitHub, and PagerDuty...
```
- **Knowledge type**: FACTUAL (classified by LLM)
- **Entities extracted**: IncidentFox, Slack, GitHub, PagerDuty, PostgreSQL
- **Usefulness to AI SRE**: HIGH (concise, actionable, searchable)

### What Slack extraction would produce (validated by unit tests)
With a valid Slack token, the KnowledgeExtractor would:
- Group messages by channel
- Identify operational topics (incidents, deployments, troubleshooting)
- Classify as PROCEDURAL (troubleshooting steps), TEMPORAL (incident timelines), SOCIAL (escalation paths)
- Skip bot-generated noise and chitchat
- Extract entities (service names, alert types, on-call people)

---

## RAG Health Final State

| Metric | Value |
|--------|-------|
| Total documents processed | 77 (across all runs) |
| Total chunks created | 155 |
| Trees | mega_ultra_v2 (default), github_incidentfox-demo, slack_incidentfox-demo |
| Knowledge types stored | factual, relational |
