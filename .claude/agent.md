# Claude Code Agent Instructions for IncidentFox v0

**System:** IncidentFox - Enterprise AI SRE Platform
**Version:** 0.1.0 (v0 Customer Launch)
**Status:** Production - Running in Customer Environments
**Launch:** Week of January 13, 2026

---

## Critical Context

You are working on a **production enterprise system** deployed in **real customer environments**.

**Quality Requirements:**
- ✅ Enterprise-grade code quality
- ✅ Backwards compatibility required
- ✅ Security-first mindset
- ✅ Comprehensive testing
- ✅ Documentation for customer-visible changes

**Never:**
- ❌ Commit secrets or credentials
- ❌ Break backwards compatibility
- ❌ Skip testing on EKS cluster
- ❌ Make assumptions without verification

---

## First Steps for Any Task

### 1. Read the Knowledge Base

**ALWAYS start by reading:**
- `DEVELOPMENT_KNOWLEDGE.md` - Comprehensive dev reference (1042 lines)
- Service-specific README in relevant directory
- `docs/DOCUMENTATION_PLAN_V0.md` - Documentation structure

**Use Task tool with Explore agent** when you need to:
- Understand how a feature works across multiple files
- Find all usages of a pattern
- Explore unfamiliar codebase areas
- Answer "where" or "how" questions

Example:
```
Use Task tool: "Explore how webhook routing works from Slack event to agent run"
```

### 2. Use TodoWrite for Complex Tasks

For any task with **3+ steps or multiple services**, create a todo list:

```typescript
TodoWrite({
  todos: [
    {content: "Read webhook router code", status: "in_progress", activeForm: "Reading webhook router"},
    {content: "Add new webhook signature verification", status: "pending", activeForm: "Adding signature verification"},
    {content: "Test webhook with mock payload", status: "pending", activeForm: "Testing webhook"},
    {content: "Update customer documentation", status: "pending", activeForm: "Updating documentation"}
  ]
})
```

### 3. Use EnterPlanMode for Non-Trivial Changes

Use EnterPlanMode when:
- Adding new features that affect multiple files
- Architectural changes
- Database schema modifications
- Customer-facing changes

**Don't use for:**
- Simple bug fixes
- Documentation updates
- Single-file changes

---

## Architecture Quick Reference

### 4 Core Services

| Service | Tech | Port | Purpose |
|---------|------|------|---------|
| **agent** | Python/Poetry | 8080 | Multi-agent runtime (6 agents, 300+ tools) |
| **config_service** | Python/FastAPI | 8080 | Control plane (org tree, tokens, configs) |
| **orchestrator** | Python/FastAPI | 8080 | Webhook routing & provisioning |
| **web_ui** | Next.js/pnpm | 3000 | Admin & Team console |

### Key Patterns

**Hierarchical Config:**
- Org → Group → Team → Sub-team inheritance
- Deep merge: dicts merge recursively, lists replace
- Cache invalidation via org epoch

**Tool Pool:**
- 300+ built-in tools from catalog
- MCP servers per team
- Team-level enable/disable lists
- Execution context: `{org_id, team_node_id, user_id}`

**Webhook Routing:**
- All webhooks → Orchestrator (not Agent, not Web UI)
- Signature verification per source
- Team lookup via Config Service routing identifiers

**Dynamic Agents:**
- Agents defined in JSON config (not Python code)
- Runtime construction from team config
- Tool filtering based on team preferences

---

## Common Commands

### Getting Secrets

```bash
# OpenAI API key
kubectl get secret incidentfox-secrets -n incidentfox -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d

# Database URL
kubectl get secret incidentfox-db -n incidentfox -o jsonpath='{.data.DATABASE_URL}' | base64 -d

# List all secrets
kubectl get secrets -n incidentfox
```

### Deployment

```bash
# Login to ECR (required first)
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 103002841599.dkr.ecr.us-west-2.amazonaws.com

# Agent service
cd agent
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest
kubectl rollout restart deployment/incidentfox-agent -n incidentfox
kubectl rollout status deployment/incidentfox-agent -n incidentfox --timeout=90s

# Config service
cd config_service
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-config-service:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-config-service:latest
kubectl rollout restart deployment/incidentfox-config-service -n incidentfox

# Orchestrator
cd orchestrator
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-orchestrator:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-orchestrator:latest
kubectl rollout restart deployment/incidentfox-orchestrator -n incidentfox

# Web UI
cd web_ui
docker build --platform linux/amd64 -t 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-web-ui:latest .
docker push 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-web-ui:latest
kubectl rollout restart deployment/incidentfox-web-ui -n incidentfox
```

**CRITICAL:** Always use `--platform linux/amd64` for EKS compatibility!

### Database Migrations

```bash
cd config_service
source .env  # DATABASE_URL must be set
alembic upgrade head

# Check current
alembic current

# Create new migration
alembic revision --autogenerate -m "description"
```

### Local Testing

```bash
# Port forward
kubectl port-forward -n incidentfox svc/incidentfox-config-service 8090:8080

# View logs
kubectl logs -n incidentfox deploy/incidentfox-agent --tail=100 -f

# Pod status
kubectl get pods -n incidentfox
```

---

## Tool Usage Patterns

### When to Use Task Tool

Use `Task` tool with `subagent_type='Explore'` for:
- "How does X work across the codebase?"
- "Find all places where Y is used"
- "Understand the flow from A to B"
- Exploring unfamiliar code areas

**Examples:**
```typescript
// Good uses
Task({subagent_type: 'Explore', prompt: 'How does webhook routing work from Slack to agent run?'})
Task({subagent_type: 'Explore', prompt: 'Find all usages of execution_context pattern in tools'})

// Bad uses (use direct tools instead)
Read({file_path: '/path/to/file.py'})  // Not Task - you know the file
Grep({pattern: 'class Agent'})  // Not Task - simple search
```

### When to Use Read vs Glob vs Grep

**Use Read when:**
- You know the exact file path
- Reading specific service README
- Viewing current code before editing

**Use Glob when:**
- Finding files by name pattern
- Example: `Glob({pattern: '**/tools/*_tools.py'})`

**Use Grep when:**
- Searching for specific code pattern
- Example: `Grep({pattern: 'def.*execution_context', output_mode: 'content'})`

### When to Use Edit vs Write

**Always use Edit for existing files:**
- Preserves formatting
- Shows exact changes
- Safer than overwriting

**Only use Write for:**
- New files that don't exist
- User explicitly requested new file

---

## Adding Features

### New Integration

1. **Research first:**
   ```typescript
   Task({subagent_type: 'Explore', prompt: 'How are integrations currently structured?'})
   ```

2. **Add to database:**
   ```sql
   INSERT INTO integration_schemas (id, name, category, description, fields)
   VALUES ('datadog', 'Datadog', 'monitoring', 'Datadog APM', '[...]');
   ```

3. **Create tool file:** `agent/src/ai_agent/tools/datadog_tools.py`
   ```python
   def get_datadog_metrics(execution_context: Dict[str, Any], query: str) -> str:
       """Query Datadog metrics API.

       Args:
           execution_context: Contains org_id, team_node_id, user_id
           query: Datadog query string

       Returns:
           JSON string: {"success": bool, "result": any, "error": str}
       """
       org_id = execution_context.get("org_id")
       # Implementation
       return json.dumps({"success": True, "result": {...}})
   ```

4. **Add to catalog:** `agent/src/ai_agent/core/tools_catalog.py`

5. **Update docs:** `docs/CUSTOMER_INSTALLATION_GUIDE.md` if customer-facing

### New Agent

Agents are JSON-configured - no code changes needed!

```json
{
  "agents": {
    "security_agent": {
      "model": "gpt-4o",
      "prompt": {
        "system": "You are a security expert...",
        "instructions": ["Check CVEs", "Review best practices"]
      },
      "tools": ["scan_vulnerabilities"],
      "sub_agents": ["k8s_agent", "coding_agent"]
    }
  }
}
```

Update in Config Service, agent builder handles the rest.

### New Tool

1. **Create with execution context pattern:**
   ```python
   def my_tool(execution_context: Dict[str, Any], param: str) -> str:
       """Tool description for LLM.

       Args:
           execution_context: Runtime context
           param: Parameter description

       Returns:
           JSON string with success/error
       """
       try:
           result = do_something(param)
           return json.dumps({"success": True, "result": result})
       except Exception as e:
           return json.dumps({"success": False, "error": str(e)})
   ```

2. **Add to catalog**
3. **Write tests**

### New Webhook

1. **Add to orchestrator:** `orchestrator/src/incidentfox_orchestrator/webhooks/router.py`

2. **Implement verification:**
   ```python
   @router.post("/webhooks/my_service")
   async def my_service_webhook(request: Request):
       # 1. Verify signature
       # 2. Extract routing identifiers
       # 3. Look up team
       # 4. Trigger agent run
       # 5. Return 200 OK immediately
   ```

3. **Add secret:** `charts/incidentfox/templates/external-secrets.yaml`
4. **Update docs:** Customer setup instructions

---

## Code Conventions

### Python (agent, config_service, orchestrator)

- **Dependencies:** Poetry (NOT pip)
- **Style:** Black, line length 120
- **Type hints:** Required
- **Imports:** Absolute only
- **Errors:** Return JSON `{"success": bool, "result": any, "error": str}`
- **Logging:** Structured with correlation_id
- **Tests:** pytest

### Next.js (web_ui)

- **Package manager:** pnpm (NOT npm/yarn)
- **Style:** TypeScript strict, ESLint
- **API routes:** Proxy to backend
- **Auth:** Cookie-based `incidentfox_session_token`
- **Components:** shadcn/ui
- **State:** React hooks

### Database

- **Always Alembic** for migrations
- **Never modify existing migrations**
- **Test upgrade/downgrade**
- **Document breaking changes**

---

## File Editing Rules

1. **Always Read before Edit**
   - Understand current content
   - See existing patterns

2. **Use Edit for existing, Write for new**
   - Edit preserves context
   - Write overwrites (dangerous)

3. **No unsolicited docs**
   - Don't create *.md files without request

4. **No emojis unless requested**
   - Professional style only

5. **Match indentation**
   - Tabs vs spaces
   - Follow existing style

6. **Absolute paths only**
   - Never relative paths

---

## Documentation Maintenance

### Update These When:

| Doc | When to Update |
|-----|----------------|
| DEVELOPMENT_KNOWLEDGE.md | Major architectural changes |
| Service READMEs | Service-specific features |
| CUSTOMER_*.md | Customer-visible changes |
| docs/TECH_DEBT.md | New TODOs or completed items |

### Don't Include:

- ❌ Temporary notes
- ❌ Historical planning ("day 1 we plan...")
- ❌ Already-resolved issues
- ❌ Duplicate information

### Style:

- ✅ Clear, concise
- ✅ Code examples
- ✅ Links to related docs
- ✅ Copy-pasteable commands
- ✅ Tables for structure
- ✅ "Last Updated" dates

---

## Testing

### Before Deployment

```bash
# 1. Tests
cd agent && poetry run pytest
cd config_service && pytest

# 2. Build
docker build --platform linux/amd64 -t test:latest .

# 3. Health check
curl http://localhost:8080/health

# 4. Verify deployment
kubectl rollout status deployment/... -n incidentfox
```

### Evaluation Framework

```bash
python3 scripts/eval_agent_performance.py

# Target: ≥85 average, <60s per scenario
```

### Manual Checklist

- [ ] Helm lint passes
- [ ] All pods ready
- [ ] Health endpoints return 200
- [ ] Web UI loads
- [ ] Agent run succeeds
- [ ] Webhooks work

---

## Security

### Secrets

- **NEVER commit secrets**
- Use Kubernetes secrets
- Use AWS Secrets Manager
- Rotate regularly
- Environment vars only

### API

- Verify webhook signatures
- Bearer token auth
- Rate limiting
- Log auth failures
- Validate input

### Database

- SQLAlchemy ORM only
- No string concatenation
- Row-level security
- Connection pooling
- SSL/TLS enabled

---

## Common Issues

| Problem | Fix |
|---------|-----|
| ImagePullBackOff | Recreate imagePullSecret |
| CrashLoopBackOff | Check logs, verify env vars |
| 503 errors | Check /health endpoint |
| JSONB not saving | Use `flag_modified()` |
| Max turns exceeded | Increase max_turns (50) |
| OOM during build | Increase Docker memory to 12GB |

---

## Deployment Checklist

- [ ] Code reviewed
- [ ] Tests passing
- [ ] Docs updated
- [ ] Migrations tested
- [ ] Docker builds with `--platform linux/amd64`
- [ ] Health endpoint works
- [ ] Helm validates
- [ ] Customer docs updated (if needed)
- [ ] Rollback plan ready

---

## Customer Impact

Before changes, assess:

1. **Breaking changes?** → Migration guide needed
2. **New secrets?** → Update installation guide
3. **API changes?** → Update API docs
4. **New integrations?** → Update setup instructions
5. **Performance impact?** → Load test

---

## Related Repositories

- **aws-playground** - OTEL demo for fault injection
  - https://github.com/incidentfox/aws-playground

- **simple-fullstack-demo** - Git agent testing
  - https://github.com/incidentfox/simple-fullstack-demo

- **incidentfox-vendor-service** - License & telemetry
  - https://github.com/incidentfox/incidentfox-vendor-service
  - https://vendor.incidentfox.ai

- **website** - Marketing
  - https://github.com/incidentfox/website
  - https://incidentfox.ai

---

## Behavioral Guidelines

### Task Management

- Use TodoWrite for 3+ step tasks
- Update status as you progress
- Mark completed immediately
- Only one task "in_progress" at a time

### Planning

- Use EnterPlanMode for non-trivial implementations
- Skip for simple fixes or single-file changes
- Get user approval before major work

### Tool Selection

- Task tool for exploration
- Read for known files
- Glob for file patterns
- Grep for code searches
- Edit for existing files
- Write only for new files

### Communication

- Be concise and professional
- No emojis unless requested
- Output text directly (not via tools)
- Explain decisions briefly

---

## Remember

This is a **production system** with **real customers**.

Every change must be:
- ✅ Well-tested
- ✅ Backwards compatible
- ✅ Documented
- ✅ Secure
- ✅ Enterprise-quality

**When uncertain, ask rather than assume.**

---

## Documentation Index

- **DEVELOPMENT_KNOWLEDGE.md** - Comprehensive dev reference
- **README.md** - High-level overview
- **docs/DOCUMENTATION_PLAN_V0.md** - Documentation structure
- **docs/TECH_DEBT.md** - TODOs and tech debt
- **docs/OPERATIONS.md** - Day-to-day operations
- **docs/ARCHITECTURE_DECISIONS.md** - ADRs
- **docs/CUSTOMER_ONBOARDING_README.md** - Customer materials

Start with DEVELOPMENT_KNOWLEDGE.md for any new work!
