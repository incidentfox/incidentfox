# IncidentFox Licensing

IncidentFox uses a dual-license model.

## Summary

| Component | License | SPDX |
|-----------|---------|------|
| Core platform | [Apache License 2.0](LICENSE) | Apache-2.0 |
| Enterprise features | [Business Source License 1.1](LICENSE-ENTERPRISE) | BUSL-1.1 |

Enterprise features automatically convert to Apache 2.0 on the Change Date
(February 18, 2030) or 4 years after each version's first release, whichever
comes first.

## What is Apache 2.0 (Core)?

The core platform is fully open source. You can use, modify, and deploy it
freely, including in production, without any commercial license. This includes:

- **sre-agent** core: `sre-agent/agent.py`, `sre-agent/server.py`,
  `sre-agent/server_simple.py`, `sre-agent/events.py`, `sre-agent/config.py`,
  `sre-agent/auth.py`, `sre-agent/scripts/`, `sre-agent/.claude/`,
  `sre-agent/Dockerfile.simple`
- **slack-bot**: Slack integration layer (`slack-bot/`)
- **config-service**: Multi-tenant control plane (`config_service/`)
- **orchestrator**: Webhook routing (`orchestrator/`)
- **Helm chart**: Kubernetes deployment templates (`charts/`)
- **Local development**: `docker-compose.yml`, `Makefile`, `docs/`, `scripts/`
- **Database**: migrations and schema (`database/`)

## What is BSL 1.1 (Enterprise)?

Enterprise features are source-available under the Business Source License 1.1.
You can read, modify, and use them for development, testing, evaluation, and
non-commercial purposes. Production use requires a commercial license from
IncidentFox, Inc.

Enterprise directories:

| Directory | Description |
|-----------|-------------|
| `sre-agent/sandbox_manager.py` | gVisor K8s sandbox pod management |
| `sre-agent/sandbox_server.py` | Sandbox-internal FastAPI server |
| `sre-agent/credential-proxy/` | Zero-knowledge secret injection (Envoy + resolver) |
| `sre-agent/sandbox-router/` | Sandbox request routing |
| `sre-agent/Dockerfile` | Production hardened container image |
| `web_ui/` | Web admin console (dashboard, RBAC, audit, KB explorer) |
| `ultimate_rag/` | RAPTOR knowledge base (hierarchical RAG) |
| `ai_pipeline/` | LLM-powered knowledge extraction |
| `k8s_agent/` | Kubernetes agent service |
| `k8s_gateway/` | Kubernetes gateway service |
| `dependency_service/` | Service dependency discovery |
| `correlation_service/` | Alert correlation engine |
| `infra/` | Terraform for production EKS/RDS deployment |
| `customer-terraform/` | Customer self-hosted deployment templates |
| `teams-app/` | Microsoft Teams integration |
| `desktop/` | Desktop application |

Each enterprise directory contains a `LICENSE` file referencing the BSL 1.1.

## How to determine the license for a file

1. Check if the file has a license header — that takes precedence.
2. Check if the file's directory contains a `LICENSE` file — that applies.
3. Otherwise, the root `LICENSE` (Apache 2.0) applies.

## Commercial Licensing

For production use of enterprise features, contact: licensing@incidentfox.ai

## Contributing

Contributions to Apache 2.0 components are under Apache 2.0.
Contributions to BSL 1.1 components are under BSL 1.1.
See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
