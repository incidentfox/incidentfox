# K8s Gateway

Gateway service for IncidentFox K8s SaaS integration. Accepts outbound SSE connections from customer K8s agents and routes commands from the AI agent.

## Architecture

```
Customer Cluster          K8s Gateway          AI Agent
================          ===========          ========

k8s-agent ─────SSE──────> /agent/connect
                          /internal/execute <── K8s tools
k8s-agent <────commands──
k8s-agent ─────response─> /agent/response
```

## Endpoints

### Agent Endpoints (external)

- `GET /agent/connect` - SSE endpoint for agents to connect
- `POST /agent/response/{request_id}` - Submit command response
- `POST /agent/heartbeat` - Alternative heartbeat endpoint

### Internal Endpoints (AI agent)

- `POST /internal/execute` - Execute K8s command on connected agent
- `GET /internal/clusters` - List connected clusters
- `GET /internal/clusters/{id}` - Get cluster connection info

### Health Endpoints

- `GET /health` - Health check
- `GET /ready` - Readiness check
- `GET /metrics` - Prometheus metrics

## Configuration

Environment variables (prefix `K8S_GATEWAY_`):

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_SERVICE_URL` | Config service URL for token validation | `http://config-service:8080` |
| `HEARTBEAT_INTERVAL_SECONDS` | SSE heartbeat interval | `30` |
| `COMMAND_TIMEOUT_SECONDS` | Default command timeout | `30` |

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run locally
uvicorn k8s_gateway.main:app --reload --port 8085

# Run tests
pytest
```
