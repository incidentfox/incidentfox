# Local Development Guide

This guide covers setting up and developing IncidentFox locally.

## Table of Contents

- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [How Local Mode Works](#how-local-mode-works)
- [Development Workflow](#development-workflow)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

Get IncidentFox running locally in 3 commands:

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Add your Anthropic API key
echo "ANTHROPIC_API_KEY=sk-ant-your-api-key" >> .env

# 3. Start all services
make dev
```

That's it! The stack will:
- Start Postgres, config-service, credential-resolver, envoy, sre-agent, and slack-bot
- Run database migrations automatically
- Seed initial config from `config_service/config/local.yaml`
- Connect to Slack (if `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are configured)

### Optional: Add Slack Integration

If you want to test the Slack bot locally:

1. Create a Slack app at https://api.slack.com/apps
2. Enable Socket Mode and generate app-level token (`xapp-...`)
3. Install the app to your workspace and get bot token (`xoxb-...`)
4. Add to `.env`:
   ```bash
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_APP_TOKEN=xapp-your-app-token
   ```
5. Restart: `make restart`

See [docs/SLACK_SETUP.md](SLACK_SETUP.md) for detailed Slack app setup.

---

## Prerequisites

### Required
- **Docker** and **Docker Compose** (or Docker Desktop)
- **Anthropic API key** (get one at https://console.anthropic.com/)

### Optional
- **Slack Bot Token + App Token** (for Slack integration testing)
- **Integration API keys** (Coralogix, AWS, GitHub, etc.) for testing specific integrations

### System Requirements
- 8GB+ RAM (Docker containers need ~4GB)
- 10GB+ disk space
- macOS, Linux, or Windows with WSL2

---

## Configuration

IncidentFox uses a two-tier configuration system in local mode:

### 1. YAML Config (`config_service/config/local.yaml`)

This file stores your **structure** and is safe to commit to git (no secrets).

**What goes here:**
- Integration configurations (with `${ENV_VAR}` references for secrets)
- AI model settings
- Prompts and skills
- Security policies

**Example:**
```yaml
org_id: local
team_id: default

# AI Model
ai_model:
  provider: anthropic
  model_id: claude-sonnet-4-6

# Integrations (secrets reference .env)
integrations:
  coralogix:
    api_key: ${CORALOGIX_API_KEY}
    region: us2
    application_name: incidentfox-local
    subsystem_name: sre-agent

  aws:
    access_key_id: ${AWS_ACCESS_KEY_ID}
    secret_access_key: ${AWS_SECRET_ACCESS_KEY}
    region: us-west-2

# Prompts (customize agent behavior)
prompts:
  system_prompt: |
    You are an expert SRE assistant...
```

### 2. Environment Variables (`.env`)

This file stores **secrets** and is gitignored.

**What goes here:**
- API keys
- Tokens
- Passwords
- Any sensitive credentials

**Example:**
```bash
# Required
ANTHROPIC_API_KEY=sk-ant-your-api-key

# Optional: Enable local mode (default)
CONFIG_MODE=local

# Optional: Slack
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Optional: Integrations
CORALOGIX_API_KEY=cxtp_your-key
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
GITHUB_TOKEN=ghp_...
```

See `.env.example` for the full list of supported environment variables.

---

## How Local Mode Works

### Single Workspace, Single Config

When `CONFIG_MODE=local` (the default for local development):

- **One org**: All config lives under `org_id="local"`
- **One team**: Default team is `team_id="default"`
- **One workspace**: Slack Socket Mode connects to a single workspace

This means:
- ✅ Zero configuration needed - just set API keys and go
- ✅ YAML config maps 1:1 to what you see in Slack
- ✅ Simple mental model: local mode = local config

**Why not per-workspace orgs in local mode?**

In production, each Slack workspace gets its own org (`slack-{team_id}`). But Socket Mode (used for local dev) only supports one workspace at a time. So we use a single `local` org for simplicity - no need to manually configure team IDs.

### Config Hierarchy

IncidentFox supports hierarchical configuration:

```
org (local)
  ├─ ai_model: claude-sonnet-4
  ├─ security policies
  └─ team (default)
      ├─ integrations (team-specific)
      ├─ prompts (team-specific)
      └─ skills (team-specific)
```

**Merge rules:**
- **Dicts merge recursively** (org config + team config)
- **Lists replace entirely** (team config overrides org config)

### Startup Sequence

1. **Postgres starts** - Database for config storage
2. **config-service starts**:
   - Runs Alembic migrations
   - Seeds initial org/team from `scripts/seed_demo_data.py`
   - **Loads `config/local.yaml` and updates database** (this is the YAML seeding)
3. **Other services start** - credential-resolver, envoy, sre-agent, slack-bot
4. **Slack bot connects** - Reads config from `local/default` org/team

---

## Development Workflow

### Making Configuration Changes

#### Option 1: Edit YAML (Recommended)

1. Edit `config_service/config/local.yaml`
2. Changes are detected automatically — no restart needed

The file watcher picks up changes within ~1 second and reseeds the database. The YAML file is the source of truth; the database reflects it.

#### Option 2: Use Slack UI

1. Open Slack home tab
2. Click "Connect" or "Edit" on an integration
3. Fill in the form

Changes via the Slack UI are written back to `local.yaml` automatically. Secrets are extracted to `.env` and referenced via `${VAR}` in the YAML file.

### Adding New Integrations

1. Add to `config/local.yaml`:
   ```yaml
   integrations:
     datadog:
       api_key: ${DATADOG_API_KEY}
       app_key: ${DATADOG_APP_KEY}
       site: datadoghq.com
   ```

2. Add secrets to `.env`:
   ```bash
   DATADOG_API_KEY=your-key
   DATADOG_APP_KEY=your-app-key
   ```

3. Restart: `docker compose restart config-service slack-bot`

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f sre-agent
docker compose logs -f slack-bot
docker compose logs -f config-service

# Last 50 lines
docker compose logs --tail 50 sre-agent
```

### Accessing Services

| Service | URL | Purpose |
|---------|-----|---------|
| **config-service** | http://localhost:8080 | Config API, health checks |
| **sre-agent** | http://localhost:8000 | Agent API, investigations |
| **envoy** | http://localhost:8001 | Credential proxy |
| **postgres** | localhost:5432 | Database (user: `incidentfox`, db: `incidentfox`) |

### Database Access

```bash
# Connect to Postgres
docker exec -it incidentfox-postgres psql -U incidentfox -d incidentfox

# View config
SELECT org_id, node_id, node_type, config_json FROM node_configurations;

# View audit log
SELECT * FROM config_audit_log ORDER BY timestamp DESC LIMIT 10;
```

### Rebuilding Services

```bash
# Rebuild all services
make rebuild

# Rebuild specific service
docker compose build config-service --no-cache
docker compose up -d config-service

# Force recreate containers
docker compose up -d --force-recreate
```

### Clean Slate

```bash
# Stop and remove containers + volumes
make clean

# Or manually
docker compose down -v
```

**Warning:** This deletes all data including Postgres volumes.

---

## Architecture Decisions

### Why CONFIG_MODE=local?

**Problem:** In production, we need multi-tenancy - each Slack workspace gets its own org. But in local dev, we want simplicity.

**Solution:** When `CONFIG_MODE=local`:
- Config service reads from `config/local.yaml` on startup
- Slack bot uses `org_id="local"` instead of `slack-{team_id}`
- Everything maps to a single local org/team

This gives developers a simple, zero-config experience while production can still use multi-tenant architecture.

### Why YAML + .env?

**Problem:** Need a declarative config file (committable) but can't commit secrets.

**Solution:** Two-tier config:
- **YAML** = structure (safe to commit)
- **.env** = secrets (gitignored)
- YAML uses `${ENV_VAR}` references to pull secrets from .env

This pattern is common in Docker Compose, Kubernetes, and most modern devops tools.

### Why Force Reload on Startup?

The `seed_from_yaml` function uses `force=True` in local mode. This ensures the YAML file is the source of truth - even if the database already has config, we overwrite it with the YAML on every restart.

**Why:** In local dev, you might manually edit the database, restart, and expect your YAML to be restored. Force reload prevents drift.

---

## Troubleshooting

### Slack bot doesn't show integrations

**Check 1:** Is CONFIG_MODE set?
```bash
docker exec incidentfox-slack-bot env | grep CONFIG_MODE
# Should show: CONFIG_MODE=local
```

**Check 2:** Is config seeded?
```bash
docker logs incidentfox-config-service | grep "Config seeding completed"
# Should see: ✅ Config seeding completed successfully
```

**Check 3:** Are integrations in database?
```bash
docker exec incidentfox-postgres psql -U incidentfox -d incidentfox -c \
  "SELECT config_json->'integrations' FROM node_configurations WHERE org_id='local' AND node_id='default';"
```

**Fix:** Restart config-service and slack-bot:
```bash
docker compose restart config-service slack-bot
```

### Port already in use

**Error:** `Error starting userland proxy: listen tcp4 0.0.0.0:5432: bind: address already in use`

**Fix:** Stop conflicting services or change ports in `docker-compose.yml`:
```bash
# Find what's using the port
lsof -i :5432

# Kill it or change docker-compose.yml ports
```

### Database migration fails

**Error:** `Can't locate revision identified by 'xxxxx'`

**Fix:** Clean slate and restart:
```bash
docker compose down -v  # Remove volumes
make dev  # Fresh start
```

### API key not working

**Check 1:** Is it in .env?
```bash
grep ANTHROPIC_API_KEY .env
```

**Check 2:** Did you restart after adding it?
```bash
docker compose restart
```

**Check 3:** Is the key valid?
```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-5-sonnet-20241022","max_tokens":1024,"messages":[{"role":"user","content":"Hi"}]}'
```

### Service won't start

**Check logs:**
```bash
docker compose logs config-service
docker compose logs sre-agent
docker compose logs slack-bot
```

**Common issues:**
- Missing required env vars
- Database not ready (wait for healthcheck)
- Port conflicts
- Out of memory (Docker Desktop needs 4GB+ allocated)

### Slack bot exits immediately

**Expected behavior:** If `SLACK_BOT_TOKEN` or `SLACK_APP_TOKEN` are not set, the bot exits gracefully with:
```
⚠️  Slack credentials not configured
Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env to enable Slack integration
```

This is normal - the bot requires both tokens. Add them to `.env` and restart.

---

## Next Steps

- [Slack Setup Guide](SLACK_SETUP.md) - Create a Slack app for local testing
- [Deployment Guide](DEPLOYMENT.md) - Deploy to production
- [Integrations](INTEGRATIONS.md) - Configure observability tools
- [Architecture](ARCHITECTURE.md) - Understand the system design

---

## Getting Help

- **GitHub Issues:** https://github.com/incidentfox/incidentfox/issues
- **Slack Community:** https://join.slack.com/t/incidentfox/shared_invite/...
- **Email:** founders@incidentfox.ai
