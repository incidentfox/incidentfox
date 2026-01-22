# IncidentFox Local Development

Run IncidentFox AI SRE locally on your terminal for evaluation and development.

## Quick Start

**First-time setup (interactive):**
```bash
make quickstart
```
This will prompt for your OpenAI API key, start all services, and launch the CLI.

**Already configured?**
```bash
make run
```
Starts services (if needed) and launches the CLI.

**Manual setup (step-by-step):**
```bash
make setup                       # Create .env
# Edit .env and set OPENAI_API_KEY=sk-xxx
make start                       # Start services
make seed                        # Generate team token
make cli                         # Launch CLI
```

## What's Included

| Service | Port | Description |
|---------|------|-------------|
| **PostgreSQL** | 5432 | Database for configuration and audit logs |
| **Config Service** | 8080 | Team configuration, tokens, feature flags |
| **Agent** | 8081 | Multi-agent AI execution (Planner + sub-agents) |
| **Web UI** | 3000 | Browser-based configuration (optional) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     LOCAL TERMINAL                              │
│                                                                 │
│  incidentfox> investigate pod crashes in production             │
│  🔍 Investigating...                                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   PLANNER AGENT                          │   │
│  │     Orchestrates investigation, delegates to sub-agents  │   │
│  │                                                          │   │
│  │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │   │ K8s Agent│ │AWS Agent │ │ Metrics  │ │ Coding   │  │   │
│  │   │ 9 tools  │ │ 8 tools  │ │ 22 tools │ │ 15 tools │  │   │
│  │   └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  ┌────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │ PostgreSQL │◀─│ Config Service │◀─│   Agent Service    │   │
│  │   :5432    │  │     :8080      │  │       :8081        │   │
│  └────────────┘  └────────────────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Commands

### Quick Commands

```bash
make quickstart  # First-time: setup + prompt for API key + start + cli
make run         # Start services (if needed) + launch CLI
```

### Service Management

```bash
make start       # Start required services (postgres, config, agent)
make start-ui    # Start with Web UI at http://localhost:3000
make stop        # Stop all services
make restart     # Restart all services
make logs        # Follow all logs
make logs-agent  # Follow agent logs only
make status      # Show service status and health
```

### CLI

```bash
make cli         # Start interactive CLI REPL (requires services running)
```

### Utilities

```bash
make shell       # Open bash in agent container
make db-shell    # Open psql in postgres
make clean       # Remove containers and volumes
```

## CLI Usage

```
incidentfox> help

## Commands
| Command       | Description                    |
|---------------|--------------------------------|
| help          | Show this help                 |
| agents        | List available agents          |
| use <agent>   | Switch to different agent      |
| clear         | Clear screen                   |
| quit          | Exit CLI                       |

## Example Prompts

incidentfox> Check if there are any k8s pods crashing
incidentfox> Check if there's any grafana metric anomaly
incidentfox> What GitHub PRs were merged in the last 24 hours?
```

## Configuration

### Required

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key for LLM inference |

### Optional Integrations

Add these to `.env` to enable additional tools:

| Variable | Tools Enabled |
|----------|---------------|
| `K8S_ENABLED=true` | Kubernetes: list_pods, get_pod_logs, describe_pod, etc. |
| `GITHUB_TOKEN` | GitHub: search_code, read_file, list_pull_requests |
| `SLACK_BOT_TOKEN` | Slack: search_messages, get_channel_history |
| `AWS_ENABLED=true` | AWS: describe_ec2, get_cloudwatch_logs, etc. |
| `DATADOG_API_KEY` | Datadog: query_metrics, search_logs |
| `GRAFANA_URL` | Grafana: query_metrics, get_dashboard |

### Example .env

```bash
# Required
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o-mini

# Auto-generated (don't edit)
TOKEN_PEPPER=xxx
TEAM_TOKEN=xxx

# Optional: Enable Kubernetes tools
K8S_ENABLED=true

# Optional: Enable GitHub tools
GITHUB_TOKEN=ghp_xxx
```

## Web UI (Optional)

Start the Web UI for browser-based configuration:

```bash
make start-ui
# Open http://localhost:3000
```

Login with your team token (from `.env`).

## Troubleshooting

### Services won't start

```bash
# Check Docker is running
docker ps

# Check logs
make logs

# Rebuild images
make build
make start
```

### "OPENAI_API_KEY not set"

Edit `.env` and add your OpenAI API key:
```bash
OPENAI_API_KEY=sk-your-key-here
```

### "TEAM_TOKEN not set"

Use `make run` which handles this automatically:
```bash
make run
```

Or run `make seed` manually after services are started:
```bash
make start
make seed
make cli
```

### Agent returns errors

Check agent logs:
```bash
make logs-agent
```

Common issues:
- Invalid API key
- Tool not enabled (add token to .env)
- Service not healthy (run `make status`)

### Reset everything

```bash
make clean      # Remove containers and volumes
make start      # Start fresh
make seed       # Generate new token
```

## Development

### Install CLI locally (for development)

```bash
pip install -e .
```

### Run CLI without Docker

If you have the services running, you can run the CLI directly:

```bash
export TEAM_TOKEN=your-token
export AGENT_URL=http://localhost:8081
python -m incidentfox_cli
```

## Cost Estimate

| Usage | Estimated Cost |
|-------|----------------|
| Light (5-10 investigations/day) | $20-50/week |
| Medium (20-30 investigations/day) | $100-200/week |
| Heavy (50+ investigations/day) | $300-500/week |

Costs depend on investigation complexity and token usage.
