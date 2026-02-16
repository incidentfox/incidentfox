---
name: knowledge-raptor
description: Search the RAPTOR knowledge base for runbooks, past incidents, service dependencies, and accumulated team knowledge. Use BEFORE Confluence when investigating incidents — this contains curated, structured knowledge that the system has learned from past investigations.
allowed-tools: Bash(python *)
---

# Knowledge Base - RAPTOR Integration

## Authentication

**No credentials needed.** The RAPTOR service is an internal Kubernetes service. Requests go directly via ClusterIP — no proxy, no tokens. Just run the scripts.

---

## Why RAPTOR Matters During Incidents

The RAPTOR knowledge base contains **learned knowledge** from past investigations, taught runbooks, service dependency graphs, and incident patterns. Check it **before** Confluence:

- **Is there a known fix?** Search for runbooks matching the symptoms
- **Has this happened before?** Find similar past incidents and their resolutions
- **What's the blast radius?** Query the service dependency graph
- **What should I know?** Search for relevant team knowledge

## Available Scripts

All scripts are in `.claude/skills/knowledge-raptor/scripts/`

### search.py - General Knowledge Search

Search across all knowledge (runbooks, docs, past learnings) using semantic search.

```bash
python .claude/skills/knowledge-raptor/scripts/search.py --query SEARCH_QUERY [--tree TREE] [--top-k N]

# Examples:
python .claude/skills/knowledge-raptor/scripts/search.py --query "how to debug OOMKilled pods"
python .claude/skills/knowledge-raptor/scripts/search.py --query "database connection pool exhaustion" --top-k 10
python .claude/skills/knowledge-raptor/scripts/search.py --query "Redis cache eviction" --tree mega_ultra_v2
```

### search_incident.py - Incident-Aware Search

Find runbooks and past incidents matching specific symptoms. Optimized for incident investigation.

```bash
python .claude/skills/knowledge-raptor/scripts/search_incident.py --symptoms DESCRIPTION [--service SERVICE] [--top-k N]

# Examples:
python .claude/skills/knowledge-raptor/scripts/search_incident.py --symptoms "pods keep crashing with OOMKilled"
python .claude/skills/knowledge-raptor/scripts/search_incident.py --symptoms "high latency on API endpoints" --service payment-gateway
python .claude/skills/knowledge-raptor/scripts/search_incident.py --symptoms "503 errors, connection timeouts" --service auth-service --top-k 10
```

### query_graph.py - Service Dependency Graph

Query the knowledge graph for service dependencies, ownership, blast radius, and related runbooks.

```bash
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity ENTITY --query-type TYPE [--max-hops N]

# Query types: dependencies, dependents, owner, runbooks, incidents, blast_radius

# Examples:
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity payment-gateway --query-type blast_radius
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity redis-cache --query-type dependents
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity auth-service --query-type owner
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity postgres-primary --query-type dependencies --max-hops 3
```

### find_similar.py - Find Similar Past Incidents

Find past incidents with similar symptoms to identify patterns and known resolutions.

```bash
python .claude/skills/knowledge-raptor/scripts/find_similar.py --symptoms DESCRIPTION [--service SERVICE] [--limit N]

# Examples:
python .claude/skills/knowledge-raptor/scripts/find_similar.py --symptoms "connection timeouts to database"
python .claude/skills/knowledge-raptor/scripts/find_similar.py --symptoms "high memory usage, pods restarting" --service checkout-service
python .claude/skills/knowledge-raptor/scripts/find_similar.py --symptoms "kafka consumer lag increasing" --limit 10
```

### teach.py - Teach New Knowledge

Teach the knowledge base something new learned during an investigation. The system detects duplicates and contradictions automatically.

```bash
python .claude/skills/knowledge-raptor/scripts/teach.py --content KNOWLEDGE [--type TYPE] [--entities ENTITY1,ENTITY2] [--confidence N] [--source SOURCE] [--context CONTEXT]

# Knowledge types: procedural, factual, temporal, relational, contextual, policy, social, meta

# Examples:
python .claude/skills/knowledge-raptor/scripts/teach.py \
  --content "When payment-gateway shows OOMKilled, check the Redis connection pool first — stale connections accumulate during traffic spikes" \
  --type procedural \
  --entities payment-gateway,redis-cache \
  --source "incident_INC-2024-0456"

python .claude/skills/knowledge-raptor/scripts/teach.py \
  --content "The auth-service fallback to database sessions adds ~200ms latency per request when Redis is down" \
  --type factual \
  --entities auth-service,redis-cache \
  --confidence 0.9
```

---

## Common Workflows

### 1. Investigate an Incident

```bash
# Step 1: Search for matching runbooks and past incidents
python .claude/skills/knowledge-raptor/scripts/search_incident.py --symptoms "503 errors, high latency" --service payment-gateway

# Step 2: Check blast radius
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity payment-gateway --query-type blast_radius

# Step 3: Find similar past incidents
python .claude/skills/knowledge-raptor/scripts/find_similar.py --symptoms "503 errors on payment service"

# Step 4: After resolving, teach what you learned
python .claude/skills/knowledge-raptor/scripts/teach.py \
  --content "payment-gateway 503s were caused by connection pool exhaustion after Redis failover" \
  --type procedural \
  --entities payment-gateway,redis-cache
```

### 2. Understand Service Dependencies

```bash
# What does this service depend on?
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity checkout-service --query-type dependencies

# Who owns it?
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity checkout-service --query-type owner

# What breaks if it goes down?
python .claude/skills/knowledge-raptor/scripts/query_graph.py --entity checkout-service --query-type blast_radius
```

### 3. Learn from History

```bash
# Search for past learnings about a topic
python .claude/skills/knowledge-raptor/scripts/search.py --query "kafka consumer rebalance storms"

# Find similar incidents
python .claude/skills/knowledge-raptor/scripts/find_similar.py --symptoms "kafka consumer group rebalancing frequently"
```

---

## Quick Commands Reference

| Goal | Command |
|------|---------|
| Find runbook | `search_incident.py --symptoms "..." --service SVC` |
| General search | `search.py --query "..."` |
| Service dependencies | `query_graph.py --entity SVC --query-type dependencies` |
| Blast radius | `query_graph.py --entity SVC --query-type blast_radius` |
| Who owns service | `query_graph.py --entity SVC --query-type owner` |
| Past incidents | `find_similar.py --symptoms "..."` |
| Teach knowledge | `teach.py --content "..." --type procedural` |

---

## Best Practices

### When to Use RAPTOR vs Confluence

1. **Start with RAPTOR** — it has structured, learned knowledge from past investigations
2. **Fall back to Confluence** — for detailed documentation, architecture docs, or team wikis
3. **Teach back to RAPTOR** — after resolving, teach what you learned so future investigations benefit

### Investigation Flow

1. **Start with incident search** — match symptoms to known patterns
2. **Check dependencies** — understand the blast radius before making changes
3. **Search broadly** — if incident search doesn't match, try general search
4. **Look at history** — find similar past incidents for resolution patterns
5. **Teach what you learn** — close the loop for future investigators
