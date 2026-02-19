#!/usr/bin/env python3
"""
Stress test for the IncidentFox self-learning system.

Teaches 50 knowledge items across all knowledge types, including:
- Messy, realistic incident notes with typos and abbreviations
- Deliberate contradictions between items
- Overlapping knowledge across services
- Temporal updates (old advice superseded by new)

Then runs 20 hard queries designed to test:
- Semantic understanding (not just keyword match)
- Contradiction detection
- Cross-entity reasoning
- Temporal reasoning (newer knowledge should win)
- Negative queries (asking about things NOT taught)
- Paraphrased queries (same intent, different words)

Usage:
    # Start the stack first:
    #   cd local && make start-raptor
    #
    # Then run:
    python3 local/test_stress_e2e.py --raptor-url http://localhost:8000
"""

import argparse
import sys
import time

import httpx

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

# ═══════════════════════════════════════════════════════════════════
# KNOWLEDGE CORPUS — 50 items
# ═══════════════════════════════════════════════════════════════════

KNOWLEDGE_ITEMS = [
    # ── Procedural (runbook-style) ──────────────────────────────
    {
        "id": "K01",
        "content": "When payment-service returns HTTP 503, check the PostgreSQL connection pool first. Default pool size is 20. During peak hours (9-11am EST), increase to 50 via: kubectl set env deployment/payment-service DB_POOL_SIZE=50",
        "knowledge_type": "procedural",
        "source": "runbook/payment-service",
        "confidence": 0.95,
        "related_entities": ["payment-service", "postgresql"],
    },
    {
        "id": "K02",
        "content": "To restart payment-service safely: kubectl rollout restart deployment/payment-service. NEVER use kubectl delete pod — it causes 30-60s of downtime. The rolling restart keeps at least 2 replicas serving traffic.",
        "knowledge_type": "procedural",
        "source": "runbook/payment-service",
        "confidence": 0.98,
        "related_entities": ["payment-service"],
    },
    {
        "id": "K03",
        "content": "auth-service login failures spike? Check Redis session store first. If Redis memory > 80%, flush expired sessions: redis-cli -h redis-auth FLUSHDB. Warning: this logs out all users.",
        "knowledge_type": "procedural",
        "source": "runbook/auth-service",
        "confidence": 0.85,
        "related_entities": ["auth-service", "redis-auth"],
    },
    {
        "id": "K04",
        "content": "order-processing stuck in PENDING state usually means Kafka consumer lag > 10k. Check with: kubectl exec kafka-0 -- kafka-consumer-groups.sh --describe --group order-processors. Fix: scale order-processor replicas to 6.",
        "knowledge_type": "procedural",
        "source": "runbook/order-processing",
        "confidence": 0.90,
        "related_entities": ["order-processing", "kafka"],
    },
    {
        "id": "K05",
        "content": "notification-service email delivery failures: check SES bounce rate in CloudWatch. If bounce rate > 5%, SES may have throttled the account. Escalate to platform team for SES sandbox review.",
        "knowledge_type": "procedural",
        "source": "runbook/notification-service",
        "confidence": 0.88,
        "related_entities": ["notification-service", "ses", "cloudwatch"],
    },
    {
        "id": "K06",
        "content": "search-service returning stale results? Elasticsearch index refresh interval is 30s by default. For real-time needs, set refresh_interval to 1s but WARNING: this 10x increases CPU usage on es-data nodes.",
        "knowledge_type": "procedural",
        "source": "runbook/search-service",
        "confidence": 0.82,
        "related_entities": ["search-service", "elasticsearch"],
    },
    {
        "id": "K07",
        "content": "CDN cache invalidation: use aws cloudfront create-invalidation --distribution-id E1ABC2DEF --paths '/*'. Takes 5-10 minutes to propagate globally. For single files, specify exact path instead of wildcard.",
        "knowledge_type": "procedural",
        "source": "runbook/cdn",
        "confidence": 0.92,
        "related_entities": ["cloudfront", "cdn"],
    },
    {
        "id": "K08",
        "content": "database migration failed mid-flight? DO NOT re-run the migration. Check pg_locks for blocked transactions: SELECT * FROM pg_locks WHERE NOT granted; Kill blocking PIDs then run migration with --skip-completed flag.",
        "knowledge_type": "procedural",
        "source": "runbook/database",
        "confidence": 0.95,
        "related_entities": ["postgresql"],
    },
    # ── Factual (service specs) ─────────────────────────────────
    {
        "id": "K09",
        "content": "payment-service runs 4 replicas in prod, 2 in staging. Uses PostgreSQL 15.3 with pgbouncer. Memory limit 512Mi, CPU limit 500m. Health check endpoint: /healthz on port 8080.",
        "knowledge_type": "factual",
        "source": "service-catalog",
        "confidence": 0.99,
        "related_entities": ["payment-service", "postgresql", "pgbouncer"],
    },
    {
        "id": "K10",
        "content": "redis-cache cluster: 3 nodes, maxmemory 4GB per node, allkeys-lru eviction policy. Used by: auth-service (sessions), cart-service (temp carts), rate-limiter (counters). Port 6379.",
        "knowledge_type": "factual",
        "source": "service-catalog",
        "confidence": 0.95,
        "related_entities": [
            "redis-cache",
            "auth-service",
            "cart-service",
            "rate-limiter",
        ],
    },
    {
        "id": "K11",
        "content": "Kafka cluster: 5 brokers, 3 zookeeper nodes. Topics: orders (partitions=12, replication=3), notifications (partitions=6), audit-log (partitions=3, retention=90d). Broker memory: 8Gi each.",
        "knowledge_type": "factual",
        "source": "service-catalog",
        "confidence": 0.97,
        "related_entities": ["kafka", "zookeeper"],
    },
    {
        "id": "K12",
        "content": "Elasticsearch cluster: 3 master, 5 data nodes. Index pattern: logs-YYYY.MM.DD, ILM policy: hot 7d → warm 30d → delete 90d. JVM heap: 16GB per data node. Version 8.11.",
        "knowledge_type": "factual",
        "source": "service-catalog",
        "confidence": 0.96,
        "related_entities": ["elasticsearch"],
    },
    # ── Messy / realistic incident notes ────────────────────────
    {
        "id": "K13",
        "content": "2024-01-15 incident: paymnt svc went down at 2:30am, turned out pgbouncer maxconns was set to 100 but we had 120 active conns. bumped to 200, came back. need to set alerts on this",
        "knowledge_type": "contextual",
        "source": "incident-notes/INC-2024-0115",
        "confidence": 0.75,
        "related_entities": ["payment-service", "pgbouncer"],
    },
    {
        "id": "K14",
        "content": "feb 3 postmortem: auth svc outage caused by expired TLS cert on redis-auth. cert was manually provisioned (not cert-manager). action item: migrate all redis TLS to cert-manager. ETA: Q2",
        "knowledge_type": "contextual",
        "source": "incident-notes/INC-2024-0203",
        "confidence": 0.80,
        "related_entities": ["auth-service", "redis-auth", "cert-manager"],
    },
    {
        "id": "K15",
        "content": "march 2024 - notification svc sending duplicate emails. root cause: kafka consumer group rebalance during deploy. fix: set max.poll.interval.ms=600000 and session.timeout.ms=45000. also added idempotency key check.",
        "knowledge_type": "contextual",
        "source": "incident-notes/INC-2024-0312",
        "confidence": 0.85,
        "related_entities": ["notification-service", "kafka"],
    },
    {
        "id": "K16",
        "content": "weird one - search-service OOMKilled 3x in a row. ES was fine, it was the sidecar envoy proxy leaking memory. envoy version 1.28 has a known leak with gRPC streams. upgraded to 1.29, fixed.",
        "knowledge_type": "contextual",
        "source": "incident-notes/INC-2024-0401",
        "confidence": 0.78,
        "related_entities": ["search-service", "envoy", "elasticsearch"],
    },
    {
        "id": "K17",
        "content": "apr 2024 prod incident: someone ran DELETE FROM orders WHERE status='pending' without a WHERE clause on created_at. wiped 45k orders. restored from point-in-time backup (RDS). took 4 hours. now we have pg_audit enabled.",
        "knowledge_type": "contextual",
        "source": "incident-notes/INC-2024-0415",
        "confidence": 0.90,
        "related_entities": ["order-processing", "postgresql", "rds"],
    },
    # ── Deliberate contradictions ───────────────────────────────
    {
        "id": "K18",
        "content": "payment-service PostgreSQL connection pool should be set to 100 connections maximum. Setting it higher causes connection thrashing and increases p99 latency.",
        "knowledge_type": "procedural",
        "source": "dba-team/guidelines",
        "confidence": 0.88,
        "related_entities": ["payment-service", "postgresql"],
        "_note": "CONTRADICTS K01 which says increase to 50 during peak",
    },
    {
        "id": "K19",
        "content": "Redis session store should NEVER be flushed in production. Instead, increase maxmemory and wait for LRU eviction. FLUSHDB causes cascading auth failures across all services.",
        "knowledge_type": "policy",
        "source": "security-team/policies",
        "confidence": 0.92,
        "related_entities": ["redis-auth", "auth-service"],
        "_note": "CONTRADICTS K03 which recommends FLUSHDB",
    },
    {
        "id": "K20",
        "content": "Elasticsearch refresh_interval should NEVER be set below 5s in production. The 2023 outage (INC-2023-0917) was caused by setting it to 1s which saturated the I/O on data nodes.",
        "knowledge_type": "policy",
        "source": "platform-team/policies",
        "confidence": 0.93,
        "related_entities": ["elasticsearch", "search-service"],
        "_note": "CONTRADICTS K06 which suggests setting to 1s",
    },
    # ── Relational (dependencies) ───────────────────────────────
    {
        "id": "K21",
        "content": "payment-service depends on: postgresql (primary DB), pgbouncer (conn pooling), redis-cache (idempotency keys), kafka (order events), vault (API keys & secrets). Critical path: payment-service → pgbouncer → postgresql.",
        "knowledge_type": "relational",
        "source": "architecture/dependencies",
        "confidence": 0.97,
        "related_entities": [
            "payment-service",
            "postgresql",
            "pgbouncer",
            "redis-cache",
            "kafka",
            "vault",
        ],
    },
    {
        "id": "K22",
        "content": "auth-service depends on: redis-auth (sessions), postgresql (user DB), ldap-proxy (SSO), vault (JWT signing keys). If redis-auth is down, auth-service falls back to DB-backed sessions (10x slower).",
        "knowledge_type": "relational",
        "source": "architecture/dependencies",
        "confidence": 0.94,
        "related_entities": [
            "auth-service",
            "redis-auth",
            "postgresql",
            "ldap-proxy",
            "vault",
        ],
    },
    {
        "id": "K23",
        "content": "order-processing depends on: kafka (event bus), payment-service (payment verification), inventory-service (stock check), notification-service (order confirmation). Failure in any blocks order completion.",
        "knowledge_type": "relational",
        "source": "architecture/dependencies",
        "confidence": 0.93,
        "related_entities": [
            "order-processing",
            "kafka",
            "payment-service",
            "inventory-service",
            "notification-service",
        ],
    },
    {
        "id": "K24",
        "content": "If PostgreSQL goes down, affected services: payment-service (hard down), auth-service (degraded - falls back to cache), order-processing (hard down), reporting-service (hard down). ETA to recover from snapshot: ~15 min.",
        "knowledge_type": "relational",
        "source": "architecture/blast-radius",
        "confidence": 0.96,
        "related_entities": [
            "postgresql",
            "payment-service",
            "auth-service",
            "order-processing",
            "reporting-service",
        ],
    },
    # ── Temporal (changing knowledge) ───────────────────────────
    {
        "id": "K25",
        "content": "As of January 2024, payment-service uses Stripe API v2023-12-15. Do NOT upgrade to v2024-01 yet — there's a breaking change in the webhook signature verification.",
        "knowledge_type": "temporal",
        "source": "engineering-updates/2024-01",
        "confidence": 0.85,
        "related_entities": ["payment-service", "stripe"],
    },
    {
        "id": "K26",
        "content": "UPDATE March 2024: Stripe API upgraded to v2024-03. The webhook signature issue from January has been fixed by Stripe. All services should use v2024-03 now.",
        "knowledge_type": "temporal",
        "source": "engineering-updates/2024-03",
        "confidence": 0.92,
        "related_entities": ["payment-service", "stripe"],
    },
    {
        "id": "K27",
        "content": "Q1 2024: We migrated from self-hosted Kafka to AWS MSK. Old broker IPs (10.0.1.x) are decommissioned. All services should use MSK endpoints: b-1.msk-prod.abc123.kafka.us-east-1.amazonaws.com:9096",
        "knowledge_type": "temporal",
        "source": "engineering-updates/2024-Q1",
        "confidence": 0.95,
        "related_entities": ["kafka", "msk"],
    },
    {
        "id": "K28",
        "content": "June 2024: Kubernetes cluster upgraded from 1.27 to 1.29. PodSecurityPolicy replaced with Pod Security Standards. Old PSP manifests will not work. Use 'restricted' profile for all new deployments.",
        "knowledge_type": "temporal",
        "source": "engineering-updates/2024-06",
        "confidence": 0.93,
        "related_entities": ["kubernetes"],
    },
    # ── Policy / compliance ─────────────────────────────────────
    {
        "id": "K29",
        "content": "PCI-DSS: payment-service logs must NOT contain full card numbers, CVV, or cardholder names. Use tokenized references only. Violation = immediate SEV1 + compliance notification within 24h.",
        "knowledge_type": "policy",
        "source": "compliance/pci-dss",
        "confidence": 0.99,
        "related_entities": ["payment-service"],
    },
    {
        "id": "K30",
        "content": "GDPR: user data deletion requests must be processed within 30 days. The deletion pipeline: auth-service → user-db → elasticsearch (remove from search index) → S3 (purge backups older than request date).",
        "knowledge_type": "policy",
        "source": "compliance/gdpr",
        "confidence": 0.98,
        "related_entities": ["auth-service", "elasticsearch", "s3"],
    },
    {
        "id": "K31",
        "content": "All production database access requires MFA + VPN + approval in PagerDuty. Direct psql connections are blocked by security group. Use the bastion host: ssh -J bastion.internal psql-proxy.internal",
        "knowledge_type": "policy",
        "source": "security-team/access-policy",
        "confidence": 0.97,
        "related_entities": ["postgresql", "bastion"],
    },
    {
        "id": "K32",
        "content": "Secret rotation policy: all API keys rotated every 90 days via Vault. Services must read secrets from Vault at startup, never hardcode. Exception: legacy notification-service still uses env vars (migration planned Q3).",
        "knowledge_type": "policy",
        "source": "security-team/secrets",
        "confidence": 0.94,
        "related_entities": ["vault", "notification-service"],
    },
    # ── Social / team knowledge ─────────────────────────────────
    {
        "id": "K33",
        "content": "payment-service owned by Team Payments (Slack: #team-payments). On-call rotation: PagerDuty schedule 'payments-oncall'. Escalation: engineer → team lead (Sarah) → VP Eng (Mike) after 30min.",
        "knowledge_type": "social",
        "source": "team-directory",
        "confidence": 0.90,
        "related_entities": ["payment-service"],
    },
    {
        "id": "K34",
        "content": "Kafka/messaging infra owned by Platform Team (Slack: #platform-eng). For MSK issues, page platform-oncall. They also own: service mesh (Istio), CI/CD (ArgoCD), observability stack (Datadog).",
        "knowledge_type": "social",
        "source": "team-directory",
        "confidence": 0.88,
        "related_entities": ["kafka", "msk", "istio", "argocd", "datadog"],
    },
    {
        "id": "K35",
        "content": "DBA team handles all PostgreSQL and Redis issues. Slack: #dba-support. For emergency DB access, page 'dba-oncall'. They can approve emergency connection pool changes within 5min during incidents.",
        "knowledge_type": "social",
        "source": "team-directory",
        "confidence": 0.87,
        "related_entities": ["postgresql", "redis-cache", "redis-auth"],
    },
    # ── More messy / realistic entries ──────────────────────────
    {
        "id": "K36",
        "content": "cart-service uses redis-cache for temp carts. TTL = 24h. if redis goes down, carts are lost but users can re-add items. not great UX but acceptable per product team. we should probably persist to dynamo as backup tbh",
        "knowledge_type": "contextual",
        "source": "slack-archive/#eng-discussion",
        "confidence": 0.65,
        "related_entities": ["cart-service", "redis-cache", "dynamodb"],
    },
    {
        "id": "K37",
        "content": "PSA: dont use kubectl exec to debug payment-service pods in prod. use the debug sidecar instead: kubectl debug -it payment-service-xyz --image=debug-tools:latest --target=payment. this avoids triggering PCI audit alerts.",
        "knowledge_type": "procedural",
        "source": "slack-archive/#incidents",
        "confidence": 0.80,
        "related_entities": ["payment-service", "kubernetes"],
    },
    {
        "id": "K38",
        "content": "the inventory-service API is SLOW. p99 is 2.3s because it does a full table scan on the products table (14M rows). theres an index on sku but not on category+warehouse_id which is the hot query path. jira ticket INFRA-4521 filed.",
        "knowledge_type": "contextual",
        "source": "slack-archive/#performance",
        "confidence": 0.72,
        "related_entities": ["inventory-service", "postgresql"],
    },
    {
        "id": "K39",
        "content": "monitoring gap: we have no alerts on kafka consumer lag for the audit-log topic. discovered during SOC2 audit. need to add datadog monitor: kafka.consumer.lag > 50000 for group=audit-writers. priority: HIGH",
        "knowledge_type": "contextual",
        "source": "audit-findings/SOC2-2024",
        "confidence": 0.88,
        "related_entities": ["kafka", "datadog", "audit-log"],
    },
    # ── Edge cases and nuanced knowledge ────────────────────────
    {
        "id": "K40",
        "content": "rate-limiter uses redis-cache with a sliding window algorithm. Default: 100 req/s per API key. Premium tier: 1000 req/s. If rate-limiter itself is down, the API gateway falls back to a static 50 req/s limit.",
        "knowledge_type": "factual",
        "source": "architecture/rate-limiting",
        "confidence": 0.91,
        "related_entities": ["rate-limiter", "redis-cache", "api-gateway"],
    },
    {
        "id": "K41",
        "content": "Circuit breaker config for payment-service → postgresql: failure threshold=5, reset timeout=30s, half-open max=3. When circuit opens, payment-service returns 503 with retry-after header. This is EXPECTED behavior, not a bug.",
        "knowledge_type": "factual",
        "source": "architecture/resilience",
        "confidence": 0.93,
        "related_entities": ["payment-service", "postgresql"],
    },
    {
        "id": "K42",
        "content": "Blue/green deployments: payment-service uses blue/green via ArgoCD. Rollback command: argocd app rollback payment-service. Takes ~2min. Canary deployments used for: search-service, recommendation-service.",
        "knowledge_type": "procedural",
        "source": "deployment/strategies",
        "confidence": 0.89,
        "related_entities": ["payment-service", "argocd", "search-service"],
    },
    {
        "id": "K43",
        "content": "backup schedule: PostgreSQL — hourly WAL archiving + daily full backup to S3 (s3://prod-db-backups/). Retention: 30 days. Point-in-time recovery available for last 7 days. RPO=1h, RTO=15min.",
        "knowledge_type": "factual",
        "source": "operations/backup",
        "confidence": 0.96,
        "related_entities": ["postgresql", "s3"],
    },
    {
        "id": "K44",
        "content": "SSL/TLS certificates: all inter-service communication uses mTLS via Istio. External certs managed by cert-manager with Let's Encrypt. Cert renewal happens automatically 30 days before expiry. Exception: redis-auth (see INC-2024-0203).",
        "knowledge_type": "factual",
        "source": "security/tls",
        "confidence": 0.91,
        "related_entities": ["istio", "cert-manager", "redis-auth"],
    },
    # ── More contradictions and updates ─────────────────────────
    {
        "id": "K45",
        "content": "payment-service health check is on /health port 3000. The readiness probe checks PostgreSQL connectivity and returns 503 if DB is unreachable.",
        "knowledge_type": "factual",
        "source": "legacy-docs/payment-service",
        "confidence": 0.70,
        "related_entities": ["payment-service"],
        "_note": "CONTRADICTS K09 which says /healthz on port 8080",
    },
    {
        "id": "K46",
        "content": "order-processing Kafka consumer group was renamed from 'order-processors' to 'order-processing-v2' in the March 2024 migration to MSK. Old group name no longer exists.",
        "knowledge_type": "temporal",
        "source": "engineering-updates/2024-03",
        "confidence": 0.90,
        "related_entities": ["order-processing", "kafka", "msk"],
        "_note": "Updates K04 which references old group name",
    },
    # ── Cross-cutting concerns ──────────────────────────────────
    {
        "id": "K47",
        "content": "Datadog APM is enabled for all services. Trace sampling rate: 10% in prod, 100% in staging. To find slow traces: Datadog → APM → Traces → filter by service + p99 > 1s. Custom metrics via StatsD on localhost:8125.",
        "knowledge_type": "procedural",
        "source": "observability/apm",
        "confidence": 0.90,
        "related_entities": ["datadog"],
    },
    {
        "id": "K48",
        "content": "Log aggregation: all services log to stdout in JSON format. Collected by Datadog agent → Datadog Logs. Log retention: 15 days in Datadog, 90 days in S3 archive. Sensitive fields (email, IP) are scrubbed by the log pipeline.",
        "knowledge_type": "factual",
        "source": "observability/logging",
        "confidence": 0.92,
        "related_entities": ["datadog", "s3"],
    },
    {
        "id": "K49",
        "content": "During a major incident: 1) Page on-call via PagerDuty 2) Open incident channel in Slack (#inc-YYYYMMDD-short-title) 3) Assign incident commander 4) Post status updates every 15min 5) Write postmortem within 48h",
        "knowledge_type": "procedural",
        "source": "incident-management/process",
        "confidence": 0.95,
        "related_entities": ["pagerduty"],
    },
    {
        "id": "K50",
        "content": "Cost optimization: payment-service runs on r6g.xlarge (ARM/Graviton). Savings vs x86: ~20%. All new services should default to Graviton instances unless they need x86-specific dependencies (e.g., some ML models).",
        "knowledge_type": "policy",
        "source": "finops/guidelines",
        "confidence": 0.86,
        "related_entities": ["payment-service"],
    },
]

# ═══════════════════════════════════════════════════════════════════
# CORRECTIONS — teach wrong→right pairs
# ═══════════════════════════════════════════════════════════════════

CORRECTIONS = [
    {
        "id": "C01",
        "original_query": "How do I connect to the production database?",
        "wrong_answer": "Just use psql -h db.prod.internal -U admin",
        "correct_answer": "Production DB requires MFA + VPN + PagerDuty approval. Use bastion: ssh -J bastion.internal psql-proxy.internal. Direct connections are blocked by security groups.",
    },
    {
        "id": "C02",
        "original_query": "How do I increase payment-service replicas?",
        "wrong_answer": "kubectl scale deployment payment-service --replicas=10",
        "correct_answer": "Payment-service scaling is managed by HPA. Do NOT manually scale. If you need more capacity, increase HPA maxReplicas in the Helm chart and let ArgoCD sync.",
    },
    {
        "id": "C03",
        "original_query": "How to check Kafka topic lag?",
        "wrong_answer": "Use the old kafka-consumer-groups.sh script on kafka-0",
        "correct_answer": "Since Q1 2024 migration to MSK, use the AWS Console or Datadog: datadog monitor 'kafka.consumer.lag' grouped by consumer_group and topic. The old self-hosted kafka-0 broker no longer exists.",
    },
]

# ═══════════════════════════════════════════════════════════════════
# HARD QUERIES — 20 queries to test retrieval quality
# ═══════════════════════════════════════════════════════════════════

HARD_QUERIES = [
    # ── Semantic understanding (not keyword match) ──────────────
    {
        "id": "Q01",
        "query": "our payments are failing with 503 what do I do",
        "expect_keywords": ["connection pool", "postgresql", "pgbouncer"],
        "description": "Informal phrasing, should find K01/K41",
    },
    {
        "id": "Q02",
        "query": "users can't log in and sessions are broken",
        "expect_keywords": ["redis", "auth", "session"],
        "description": "No service names mentioned, should find K03/K22",
    },
    {
        "id": "Q03",
        "query": "emails are being sent twice to customers",
        "expect_keywords": ["kafka", "consumer", "rebalance", "idempotency"],
        "description": "Describes symptom, should find K15 (duplicate emails incident)",
    },
    {
        "id": "Q04",
        "query": "everything is super slow after we deployed",
        "expect_keywords": ["rollout", "rollback", "argocd"],
        "description": "Vague complaint, should surface deployment/rollback knowledge",
    },
    # ── Cross-entity reasoning ──────────────────────────────────
    {
        "id": "Q05",
        "query": "if postgres goes down what services are affected",
        "expect_keywords": ["payment", "auth", "order"],
        "description": "Blast radius query, should find K24",
    },
    {
        "id": "Q06",
        "query": "what depends on redis-cache",
        "expect_keywords": ["auth", "cart", "rate-limiter"],
        "description": "Dependency query, should find K10",
    },
    {
        "id": "Q07",
        "query": "what infrastructure does the payment service need to work",
        "expect_keywords": ["postgresql", "pgbouncer", "redis", "kafka", "vault"],
        "description": "Full dependency chain, should find K21",
    },
    # ── Contradiction-aware queries ─────────────────────────────
    {
        "id": "Q08",
        "query": "should I flush redis when auth-service has high memory",
        "expect_keywords": ["redis", "flush", "auth"],
        "description": "Should surface K03 AND K19 (contradicting advice about FLUSHDB)",
    },
    {
        "id": "Q09",
        "query": "what is the correct Elasticsearch refresh interval for production",
        "expect_keywords": ["refresh_interval", "production"],
        "description": "Should surface K06 AND K20 (contradicting 1s vs never-below-5s)",
    },
    {
        "id": "Q10",
        "query": "what port does payment-service health check use",
        "expect_keywords": ["health", "port"],
        "description": "Should surface K09 AND K45 (contradicting 8080 vs 3000)",
    },
    # ── Temporal reasoning ──────────────────────────────────────
    {
        "id": "Q11",
        "query": "what Stripe API version should we use",
        "expect_keywords": ["stripe", "2024"],
        "description": "Should find K26 (March update) over K25 (Jan warning)",
    },
    {
        "id": "Q12",
        "query": "how to check kafka consumer lag for order processing",
        "expect_keywords": ["kafka", "consumer", "lag"],
        "description": "Should surface both K04 and K46 (updated group name)",
    },
    # ── Compliance / policy queries ─────────────────────────────
    {
        "id": "Q13",
        "query": "can I log credit card numbers for debugging",
        "expect_keywords": ["pci", "card", "tokenized"],
        "description": "Should strongly match PCI-DSS policy K29",
    },
    {
        "id": "Q14",
        "query": "a customer wants their data deleted how long do we have",
        "expect_keywords": ["gdpr", "30 days", "deletion"],
        "description": "GDPR query, should find K30",
    },
    # ── Who to contact ──────────────────────────────────────────
    {
        "id": "Q15",
        "query": "who do I page for a kafka issue at 3am",
        "expect_keywords": ["platform", "oncall"],
        "description": "Team/escalation query, should find K34",
    },
    {
        "id": "Q16",
        "query": "I need emergency database access right now",
        "expect_keywords": ["mfa", "vpn", "bastion", "pagerduty"],
        "description": "Should find K31 (access policy) and correction C01",
    },
    # ── Paraphrased / indirect queries ──────────────────────────
    {
        "id": "Q17",
        "query": "orders are stuck and not processing",
        "expect_keywords": ["kafka", "consumer", "pending"],
        "description": "Same as K04 but different wording",
    },
    {
        "id": "Q18",
        "query": "how do we handle secret rotation and API keys",
        "expect_keywords": ["vault", "90 days", "rotation"],
        "description": "Should find K32 (secrets policy)",
    },
    # ── Harder: multi-hop reasoning ─────────────────────────────
    {
        "id": "Q19",
        "query": "payment-service is returning 503 but PostgreSQL looks healthy",
        "expect_keywords": ["pgbouncer", "circuit breaker"],
        "description": "If PG is healthy, the issue is pgbouncer (K13) or circuit breaker (K41)",
    },
    {
        "id": "Q20",
        "query": "what happened in the April 2024 data loss incident",
        "expect_keywords": ["delete", "orders", "backup", "pg_audit"],
        "description": "Should find K17 (the accidental DELETE incident)",
    },
]


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════


class StressTestRunner:
    def __init__(self, raptor_url: str):
        self.raptor_url = raptor_url.rstrip("/")
        self.client = httpx.Client(base_url=self.raptor_url, timeout=60.0)
        self.teach_results = {}
        self.query_results = {}

    def run(self):
        print("=" * 70)
        print("IncidentFox Self-Learning System — Stress Test")
        print(f"Target: {self.raptor_url}")
        print(f"Knowledge items: {len(KNOWLEDGE_ITEMS)}")
        print(f"Corrections: {len(CORRECTIONS)}")
        print(f"Hard queries: {len(HARD_QUERIES)}")
        print("=" * 70)

        # 1. Health check
        print("\n[Phase 1] Health Check")
        r = self.client.get("/health")
        if r.status_code != 200:
            print(f"  ABORT: Server not healthy ({r.status_code})")
            return False
        print(f"  Server healthy, uptime={r.json().get('uptime_seconds', '?')}s")

        # 2. Teach all knowledge
        print(f"\n[Phase 2] Teaching {len(KNOWLEDGE_ITEMS)} knowledge items...")
        created = 0
        duplicates = 0
        errors = 0
        t0 = time.time()
        for item in KNOWLEDGE_ITEMS:
            payload = {
                k: v for k, v in item.items() if not k.startswith("_") and k != "id"
            }
            r = self.client.post("/api/v1/teach", json=payload)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "unknown")
                self.teach_results[item["id"]] = {
                    "status": status,
                    "node_id": data.get("node_id"),
                }
                if status == "created":
                    created += 1
                elif status == "duplicate":
                    duplicates += 1
                else:
                    created += 1  # merged etc
            else:
                errors += 1
                self.teach_results[item["id"]] = {
                    "status": "error",
                    "code": r.status_code,
                }
        teach_time = time.time() - t0
        print(f"  Created: {created} | Duplicates: {duplicates} | Errors: {errors}")
        print(
            f"  Time: {teach_time:.1f}s ({teach_time/len(KNOWLEDGE_ITEMS)*1000:.0f}ms avg)"
        )

        # 3. Teach corrections
        print(f"\n[Phase 3] Teaching {len(CORRECTIONS)} corrections...")
        for corr in CORRECTIONS:
            r = self.client.post(
                "/teach/correction",
                params={
                    "original_query": corr["original_query"],
                    "wrong_answer": corr["wrong_answer"],
                    "correct_answer": corr["correct_answer"],
                },
            )
            status = (
                r.json().get("status", "?")
                if r.status_code == 200
                else f"err:{r.status_code}"
            )
            print(f"  {corr['id']}: {status}")

        # 4. Run maintenance to detect contradictions
        print("\n[Phase 4] Running maintenance cycle...")
        r = self.client.post("/maintenance/run")
        if r.status_code == 200:
            data = r.json()
            print(
                f"  Cycle #{data.get('cycle', '?')}: stale={data.get('stale_detected', 0)}, "
                f"gaps={data.get('gaps_detected', 0)}, contradictions={data.get('contradictions_detected', 0)}"
            )

        # 5. Maintenance report
        print("\n[Phase 5] Maintenance report...")
        r = self.client.get("/maintenance/report")
        if r.status_code == 200:
            data = r.json()
            print(f"  Total nodes: {data.get('total_nodes', '?')}")
            print(f"  Active nodes: {data.get('active_nodes', '?')}")

        # 6. Run hard queries
        print(f"\n[Phase 6] Running {len(HARD_QUERIES)} hard queries...")
        print("-" * 70)
        total_pass = 0
        total_partial = 0
        total_fail = 0

        for q in HARD_QUERIES:
            payload = {"query": q["query"], "top_k": 5}
            t0 = time.time()
            r = self.client.post("/query", json=payload)
            query_time = time.time() - t0

            if r.status_code != 200:
                print(f"\n  {q['id']}: [{FAIL}] HTTP {r.status_code}")
                total_fail += 1
                continue

            data = r.json()
            results = data.get("results", [])
            strategies = data.get("strategies_used", [])
            all_text = " ".join(res.get("text", "").lower() for res in results)

            # Check how many expected keywords appear in results
            found_keywords = []
            missing_keywords = []
            for kw in q["expect_keywords"]:
                if kw.lower() in all_text:
                    found_keywords.append(kw)
                else:
                    missing_keywords.append(kw)

            hit_ratio = (
                len(found_keywords) / len(q["expect_keywords"])
                if q["expect_keywords"]
                else 0
            )

            if hit_ratio >= 0.5:
                label = PASS
                total_pass += 1
            elif hit_ratio > 0:
                label = WARN
                total_partial += 1
            else:
                label = FAIL
                total_fail += 1

            self.query_results[q["id"]] = {
                "hit_ratio": hit_ratio,
                "found": found_keywords,
                "missing": missing_keywords,
                "num_results": len(results),
                "strategies": strategies,
                "time_ms": query_time * 1000,
            }

            print(f"\n  {q['id']}: [{label}] {q['description']}")
            print(f"      Query: \"{q['query']}\"")
            print(
                f"      Results: {len(results)} | Strategies: {', '.join(strategies)} | Time: {query_time*1000:.0f}ms"
            )
            print(f"      Keywords found: {found_keywords}")
            if missing_keywords:
                print(f"      Keywords missing: {missing_keywords}")
            if results:
                top = results[0]
                text_preview = top.get("text", "")[:100]
                print(
                    f"      Top result (score={top.get('score', '?')}): {text_preview}..."
                )

        # 7. Summary
        print("\n" + "=" * 70)
        print("STRESS TEST SUMMARY")
        print("=" * 70)
        print(
            f"\n  Knowledge taught: {created + duplicates}/{len(KNOWLEDGE_ITEMS)} ({created} new, {duplicates} dup)"
        )
        print(f"  Corrections taught: {len(CORRECTIONS)}")
        print(f"\n  Query results ({len(HARD_QUERIES)} total):")
        print(f"    [{PASS}] Pass (≥50% keywords found): {total_pass}")
        print(f"    [{WARN}] Partial (<50% keywords):     {total_partial}")
        print(f"    [{FAIL}] Fail (0 keywords found):     {total_fail}")
        print(
            f"    Hit rate: {total_pass}/{len(HARD_QUERIES)} = {total_pass/len(HARD_QUERIES)*100:.0f}%"
        )
        print(
            f"    Partial+Pass rate: {total_pass+total_partial}/{len(HARD_QUERIES)} = {(total_pass+total_partial)/len(HARD_QUERIES)*100:.0f}%"
        )

        avg_time = (
            sum(r.get("time_ms", 0) for r in self.query_results.values())
            / len(self.query_results)
            if self.query_results
            else 0
        )
        print(f"    Avg query time: {avg_time:.0f}ms")
        print("=" * 70)

        return total_fail == 0


def main():
    parser = argparse.ArgumentParser(description="Stress test for self-learning system")
    parser.add_argument(
        "--raptor-url",
        default="http://localhost:8000",
        help="Ultimate RAG server URL",
    )
    args = parser.parse_args()

    runner = StressTestRunner(args.raptor_url)
    success = runner.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
