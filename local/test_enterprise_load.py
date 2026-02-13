#!/usr/bin/env python3
"""
Enterprise-scale load test for the IncidentFox self-learning RAG system.

Ingests ~600-750 knowledge items from real SRE playbooks + synthetic enterprise
data, then benchmarks retrieval quality across 45 hard queries.

Data sources:
  - Scoutflo SRE Playbooks (259 real playbooks from GitHub, chunked to ~500-600 items)
  - Synthetic enterprise data (service catalog, teams, incidents, policies, contradictions)

Usage:
    # Start the stack first:
    #   cd local && make start-raptor
    #
    # First run (fetches playbooks from GitHub, takes ~10-15 min total):
    python3 local/test_enterprise_load.py

    # Re-run with cached playbooks:
    python3 local/test_enterprise_load.py --skip-fetch

    # Query-only (assumes data already loaded):
    python3 local/test_enterprise_load.py --skip-ingest

    # Quick run (limit playbook items):
    python3 local/test_enterprise_load.py --max-playbooks 100
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

GITHUB_REPO = "Scoutflo/Scoutflo-SRE-Playbooks"
CACHE_DIR = Path(__file__).parent / "data" / "scoutflo_playbooks"

SKIP_DIRS = {"08-Proactive", "13-Proactive"}

AWS_SERVICES = [
    "ec2",
    "rds",
    "s3",
    "vpc",
    "iam",
    "lambda",
    "ecs",
    "eks",
    "cloudwatch",
    "cloudfront",
    "route53",
    "ses",
    "sns",
    "sqs",
    "dynamodb",
    "elasticache",
    "codepipeline",
    "codebuild",
    "kms",
    "elb",
    "alb",
    "nlb",
    "nat gateway",
    "auto scaling",
    "ebs",
    "guardduty",
]
K8S_RESOURCES = [
    "pod",
    "deployment",
    "service",
    "ingress",
    "node",
    "namespace",
    "configmap",
    "secret",
    "pvc",
    "statefulset",
    "daemonset",
    "cronjob",
    "hpa",
    "rbac",
    "kubelet",
    "coredns",
    "api server",
    "etcd",
]


# ═══════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════


@dataclass
class KnowledgeItem:
    id: str
    content: str
    knowledge_type: str
    source: str
    confidence: float
    related_entities: List[str]
    category: str = ""
    subcategory: str = ""


@dataclass
class Correction:
    id: str
    original_query: str
    wrong_answer: str
    correct_answer: str


@dataclass
class BenchmarkQuery:
    id: str
    query: str
    expect_keywords: List[str]
    category: str
    description: str


@dataclass
class QueryResult:
    query_id: str
    hit_ratio: float
    found_keywords: List[str]
    missing_keywords: List[str]
    num_results: int
    strategies: List[str]
    time_ms: float
    category: str


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: FETCH & PARSE SCOUTFLO PLAYBOOKS
# ═══════════════════════════════════════════════════════════════════


class PlaybookFetcher:
    """Fetches and caches Scoutflo SRE playbooks from GitHub."""

    def __init__(self):
        self.cache_file = CACHE_DIR / "playbooks.json"

    def fetch_all(self, force_refresh: bool = False) -> List[Dict]:
        if self.cache_file.exists() and not force_refresh:
            print(f"  Loading cached playbooks from {self.cache_file}")
            with open(self.cache_file) as f:
                return json.load(f)

        print(f"  Fetching playbook list from GitHub ({GITHUB_REPO})...")
        paths = self._get_playbook_paths()
        print(f"  Found {len(paths)} playbooks to fetch")

        playbooks = []
        for i, path in enumerate(paths):
            if i % 25 == 0:
                print(f"  Fetching... {i}/{len(paths)}", flush=True)
            raw = self._fetch_file(path)
            if raw:
                playbooks.append({"path": path, "content": raw})

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(playbooks, f)
        print(f"  Cached {len(playbooks)} playbooks to {self.cache_file}")
        return playbooks

    def _get_playbook_paths(self) -> List[str]:
        tree_json = self._gh_api(f"/repos/{GITHUB_REPO}/git/trees/master?recursive=1")
        tree = json.loads(tree_json).get("tree", [])
        paths = []
        for item in tree:
            p = item.get("path", "")
            if not p.endswith(".md"):
                continue
            if not (
                p.startswith("AWS Playbooks/")
                or p.startswith("K8s Playbooks/")
                or p.startswith("Sentry Playbooks/")
            ):
                continue
            parts = p.split("/")
            if any(d in parts for d in SKIP_DIRS):
                continue
            if parts[-1].lower() == "readme.md":
                continue
            paths.append(p)
        return paths

    def _fetch_file(self, path: str) -> Optional[str]:
        try:
            raw = self._gh_api(
                f"/repos/{GITHUB_REPO}/contents/{path}",
                accept="application/vnd.github.v3.raw",
            )
            return raw
        except Exception:
            return None

    def _gh_api(
        self, endpoint: str, accept: str = "application/vnd.github.v3+json"
    ) -> str:
        """Call GitHub API using gh CLI (uses user's existing auth)."""
        cmd = ["gh", "api", endpoint, "-H", f"Accept: {accept}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"gh api failed: {result.stderr[:200]}")
        return result.stdout


class PlaybookParser:
    """Parses Scoutflo playbook markdown into knowledge chunks."""

    def parse(self, path: str, raw_md: str) -> List[KnowledgeItem]:
        content = self._strip_frontmatter(raw_md)
        title = self._extract_title(content)
        sections = self._extract_sections(content)
        category, subcategory = self._path_to_category(path)
        entities = self._extract_entities(title, content, category)
        pb_id = self._path_to_id(path)

        items = []

        # Chunk 1: Meaning + Impact → contextual
        meaning = sections.get("meaning", "")
        impact = sections.get("impact", "")
        if meaning or impact:
            combined = f"# {title}\n\n"
            if meaning:
                combined += f"## What it means\n{meaning}\n\n"
            if impact:
                combined += f"## Impact\n{impact}"
            items.append(
                KnowledgeItem(
                    id=f"PB-{pb_id}-CTX",
                    content=combined.strip(),
                    knowledge_type="contextual",
                    source=f"scoutflo/{path}",
                    confidence=0.90,
                    related_entities=entities,
                    category=category,
                    subcategory=subcategory,
                )
            )

        # Chunk 2: Playbook steps → procedural
        playbook = sections.get("playbook", "")
        if playbook and len(playbook) > 50:
            proc = f"# {title} - Remediation Steps\n\n{playbook}"
            items.append(
                KnowledgeItem(
                    id=f"PB-{pb_id}-PROC",
                    content=proc.strip(),
                    knowledge_type="procedural",
                    source=f"scoutflo/{path}",
                    confidence=0.92,
                    related_entities=entities,
                    category=category,
                    subcategory=subcategory,
                )
            )

        # Chunk 3: Diagnosis → procedural (only if substantial)
        diagnosis = sections.get("diagnosis", "")
        if diagnosis and len(diagnosis) > 200:
            diag = f"# {title} - Diagnosis Guide\n\n{diagnosis}"
            items.append(
                KnowledgeItem(
                    id=f"PB-{pb_id}-DIAG",
                    content=diag.strip(),
                    knowledge_type="procedural",
                    source=f"scoutflo/{path}",
                    confidence=0.88,
                    related_entities=entities,
                    category=category,
                    subcategory=subcategory,
                )
            )

        return items

    def _strip_frontmatter(self, content: str) -> str:
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                return content[end + 3 :].strip()
        return content

    def _extract_title(self, content: str) -> str:
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        return match.group(1).strip() if match else "Unknown Playbook"

    def _extract_sections(self, content: str) -> Dict[str, str]:
        sections = {}
        current = None
        lines = []
        for line in content.split("\n"):
            if line.startswith("## "):
                if current:
                    sections[current] = "\n".join(lines).strip()
                current = line[3:].strip().lower()
                lines = []
            elif current:
                lines.append(line)
        if current:
            sections[current] = "\n".join(lines).strip()
        return sections

    def _extract_entities(self, title: str, content: str, category: str) -> List[str]:
        entities = set()
        text = (title + " " + content).lower()
        if category == "aws":
            for svc in AWS_SERVICES:
                if svc in text:
                    entities.add(svc)
        elif category == "k8s":
            for res in K8S_RESOURCES:
                if res in text:
                    entities.add(f"k8s-{res}")
        elif category == "sentry":
            entities.add("sentry")
        entities.add(category)
        return list(entities)[:8]

    def _path_to_category(self, path: str) -> Tuple[str, str]:
        parts = path.split("/")
        cat = (
            "aws"
            if parts[0].startswith("AWS")
            else "k8s" if parts[0].startswith("K8s") else "sentry"
        )
        sub = parts[1] if len(parts) > 1 else ""
        return cat, sub

    def _path_to_id(self, path: str) -> str:
        parts = path.split("/")
        cat = parts[0][:3].upper()
        sub = parts[1][:5] if len(parts) > 1 else "00"
        name = parts[-1].replace(".md", "")[:25]
        return f"{cat}-{sub}-{name}"


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: SYNTHETIC ENTERPRISE DATA
# ═══════════════════════════════════════════════════════════════════


def build_synthetic_services() -> List[KnowledgeItem]:
    """30 microservices with specs and dependencies."""
    services = [
        (
            "payment-gateway",
            "tier-1",
            ["postgres-primary", "redis-sessions", "kafka-events", "vault"],
            "Processes payment transactions via Stripe. 4 replicas, 512Mi memory, port 8080. Health: /healthz",
        ),
        (
            "auth-service",
            "tier-1",
            ["postgres-primary", "redis-sessions", "ldap-proxy", "vault"],
            "Handles auth, JWT issuance, SSO. 3 replicas, 256Mi memory. Falls back to DB sessions if Redis down",
        ),
        (
            "order-service",
            "tier-1",
            [
                "postgres-primary",
                "kafka-events",
                "payment-gateway",
                "inventory-service",
            ],
            "Order lifecycle management. 4 replicas, 512Mi. Uses Kafka for async order events",
        ),
        (
            "inventory-service",
            "tier-2",
            ["postgres-primary", "redis-cache"],
            "Stock management. 2 replicas, 256Mi. p99=2.3s due to missing index on category+warehouse_id",
        ),
        (
            "notification-service",
            "tier-2",
            ["kafka-events", "ses", "redis-cache"],
            "Email/SMS/push. 3 replicas. Uses SES for email, Twilio for SMS. Idempotency via Redis",
        ),
        (
            "search-service",
            "tier-2",
            ["elasticsearch", "redis-cache"],
            "Product/content search. 2 replicas, 1Gi memory. Elasticsearch 8.11 backend",
        ),
        (
            "cart-service",
            "tier-2",
            ["redis-cache", "inventory-service"],
            "Shopping cart. Temp carts in Redis with 24h TTL. Carts lost if Redis restarts",
        ),
        (
            "shipping-service",
            "tier-2",
            ["postgres-primary", "kafka-events"],
            "Shipping rate calculation and tracking. Integrates with FedEx/UPS APIs",
        ),
        (
            "recommendation-service",
            "tier-3",
            ["elasticsearch", "redis-cache", "ml-model-server"],
            "Product recommendations. Canary deployment via ArgoCD. GPU-accelerated inference",
        ),
        (
            "analytics-service",
            "tier-3",
            ["kafka-events", "clickhouse", "s3"],
            "Real-time analytics pipeline. Consumes all Kafka topics. Writes to ClickHouse + S3",
        ),
        (
            "api-gateway",
            "tier-1",
            ["auth-service", "rate-limiter"],
            "Kong-based API gateway. Rate limiting, auth, routing. 3 replicas, port 443",
        ),
        (
            "rate-limiter",
            "tier-1",
            ["redis-cache"],
            "Sliding window rate limiting. 100 req/s default, 1000 req/s premium. Falls back to 50 req/s static",
        ),
        (
            "reporting-service",
            "tier-3",
            ["postgres-readonly", "s3"],
            "Business reports and exports. Uses read replica. CSV/PDF generation to S3",
        ),
        (
            "user-profile-service",
            "tier-2",
            ["postgres-primary", "redis-cache", "s3"],
            "User profiles, preferences, avatars. S3 for image storage. 2 replicas",
        ),
        (
            "webhook-service",
            "tier-2",
            ["kafka-events", "postgres-primary"],
            "Outbound webhook delivery. Retry with exponential backoff. Dead letter queue after 5 failures",
        ),
        (
            "billing-service",
            "tier-1",
            ["postgres-primary", "payment-gateway", "vault"],
            "Subscription billing, invoices, revenue recognition. PCI-DSS scoped",
        ),
        (
            "audit-service",
            "tier-2",
            ["kafka-events", "elasticsearch"],
            "SOC2 audit trail. Consumes audit-log Kafka topic. 90 day retention in ES",
        ),
        (
            "config-service",
            "tier-2",
            ["postgres-primary", "vault"],
            "Feature flags and dynamic config. Polled by all services every 30s",
        ),
        (
            "ml-model-server",
            "tier-3",
            ["s3", "redis-cache"],
            "TensorFlow Serving for ML models. GPU nodes (p3.2xlarge). Model artifacts in S3",
        ),
        (
            "cdn-service",
            "tier-2",
            ["cloudfront", "s3"],
            "Static asset serving via CloudFront. Cache invalidation takes 5-10min globally",
        ),
    ]

    items = []
    for name, tier, deps, desc in services:
        # Factual: service spec
        items.append(
            KnowledgeItem(
                id=f"SVC-{name}-SPEC",
                content=f"{name} ({tier}): {desc}",
                knowledge_type="factual",
                source="service-catalog/specs",
                confidence=0.95,
                related_entities=[name] + deps[:3],
                category="synthetic",
                subcategory="service-catalog",
            )
        )
        # Relational: dependency chain
        dep_str = ", ".join(deps)
        items.append(
            KnowledgeItem(
                id=f"SVC-{name}-DEPS",
                content=f"{name} depends on: {dep_str}. If any dependency is down, {name} may be degraded or unavailable.",
                knowledge_type="relational",
                source="architecture/dependencies",
                confidence=0.93,
                related_entities=[name] + deps,
                category="synthetic",
                subcategory="dependencies",
            )
        )

    # Blast radius items
    blast_items = [
        (
            "postgres-primary",
            [
                "payment-gateway",
                "auth-service",
                "order-service",
                "inventory-service",
                "shipping-service",
                "billing-service",
                "user-profile-service",
                "config-service",
            ],
            "If postgres-primary goes down: payment-gateway (hard down), auth-service (degraded, falls back to cached sessions), order-service (hard down), billing-service (hard down), inventory-service (hard down). ETA recovery from snapshot: ~15 min. RPO=1h.",
        ),
        (
            "redis-cache",
            [
                "cart-service",
                "rate-limiter",
                "search-service",
                "recommendation-service",
            ],
            "If redis-cache goes down: cart-service loses all temp carts (24h TTL data lost), rate-limiter falls back to static 50 req/s limit, search-service loses result cache (higher ES load), recommendation-service cache miss storm.",
        ),
        (
            "kafka-events",
            [
                "order-service",
                "notification-service",
                "analytics-service",
                "audit-service",
                "webhook-service",
            ],
            "If kafka-events goes down: order-service cannot publish order events (orders stuck in PENDING), notification-service stops sending, analytics pipeline halts, audit trail broken (SOC2 compliance risk).",
        ),
    ]
    for infra, affected, desc in blast_items:
        items.append(
            KnowledgeItem(
                id=f"BLAST-{infra}",
                content=desc,
                knowledge_type="relational",
                source="architecture/blast-radius",
                confidence=0.96,
                related_entities=[infra] + affected[:5],
                category="synthetic",
                subcategory="blast-radius",
            )
        )

    return items


def build_synthetic_teams() -> List[KnowledgeItem]:
    """10 team ownership items."""
    teams = [
        (
            "Team Payments owns payment-gateway, billing-service. Slack: #team-payments. PagerDuty: payments-oncall. Escalation: on-call (15min) → team lead Sarah Chen → VP Eng Mike (30min).",
            ["payment-gateway", "billing-service"],
        ),
        (
            "Team Commerce owns order-service, cart-service, inventory-service. Slack: #team-commerce. PagerDuty: commerce-oncall. Lead: Alex Kim.",
            ["order-service", "cart-service", "inventory-service"],
        ),
        (
            "Platform Team owns kafka-events, api-gateway, rate-limiter, config-service, ArgoCD, Istio service mesh. Slack: #platform-eng. PagerDuty: platform-oncall.",
            ["kafka-events", "api-gateway", "rate-limiter"],
        ),
        (
            "DBA Team handles all PostgreSQL, Redis, Elasticsearch issues. Slack: #dba-support. Emergency DB access: page dba-oncall. Can approve connection pool changes within 5min during incidents.",
            ["postgres-primary", "redis-cache", "elasticsearch"],
        ),
        (
            "Team Identity owns auth-service, user-profile-service, ldap-proxy. Slack: #team-identity. On-call: identity-oncall. SSO issues escalate to LDAP vendor after 30min.",
            ["auth-service", "user-profile-service"],
        ),
        (
            "SRE Team owns monitoring (Datadog), alerting (PagerDuty), incident management process. Slack: #sre-team. During major incidents: SRE assigns incident commander.",
            ["datadog", "pagerduty"],
        ),
        (
            "ML Team owns recommendation-service, ml-model-server, analytics-service. Slack: #ml-team. GPU infrastructure issues: page platform-oncall first.",
            ["recommendation-service", "ml-model-server"],
        ),
        (
            "Security Team owns vault, secret rotation policies, TLS certificates, PCI-DSS compliance. Slack: #security. Security incidents: page security-oncall immediately.",
            ["vault"],
        ),
        (
            "DevOps/Release Team owns CI/CD pipeline (ArgoCD + GitHub Actions), deployment strategies, rollback procedures. Slack: #devops.",
            ["argocd"],
        ),
        (
            "Compliance Team owns SOC2, PCI-DSS, GDPR processes. Audit requests: compliance@company.com. Data deletion SLA: 30 days.",
            [],
        ),
    ]
    return [
        KnowledgeItem(
            id=f"TEAM-{i:02d}",
            content=content,
            knowledge_type="social",
            source="team-directory",
            confidence=0.90,
            related_entities=entities,
            category="synthetic",
            subcategory="teams",
        )
        for i, (content, entities) in enumerate(teams)
    ]


def build_synthetic_incidents() -> List[KnowledgeItem]:
    """15 messy incident notes."""
    incidents = [
        (
            "2024-08-22 3:47am: payment-gateway went down. turned out someone pushed a config change to vault that rotated the stripe API key but didnt update the payment-gateway secret. took 45min to figure out. added smoke test to deploy pipeline.",
            ["payment-gateway", "vault"],
            "INC-2024-0822",
        ),
        (
            "sept 2024 postmortem: auth svc outage. expired TLS cert on redis-sessions. cert was manually provisioned (not cert-manager). action item: migrate all redis TLS to cert-manager. ETA Q1 2025.",
            ["auth-service", "redis-sessions", "cert-manager"],
            "INC-2024-0903",
        ),
        (
            "oct 14 - notification svc sending 3x duplicate emails. root cause: kafka consumer group rebalance during rolling deploy. fix: set max.poll.interval.ms=600000. also added idempotency key.",
            ["notification-service", "kafka-events"],
            "INC-2024-1014",
        ),
        (
            "weird one - search-service OOMKilled 3x. ES was fine, it was the envoy sidecar leaking mem. envoy 1.28 has known gRPC stream leak. upgraded to 1.29, fixed.",
            ["search-service", "envoy", "elasticsearch"],
            "INC-2024-1101",
        ),
        (
            "nov 2024 prod incident: someone ran DELETE FROM orders WHERE status='pending' without WHERE on created_at. wiped 45k orders. restored from PITR backup. took 4hrs. now pg_audit enabled.",
            ["order-service", "postgres-primary"],
            "INC-2024-1115",
        ),
        (
            "dec 5 3am: rate-limiter redis went OOM. all API traffic got static 50 req/s limit. customers noticed immediately. bumped maxmemory from 2GB to 4GB, added memory alert.",
            ["rate-limiter", "redis-cache"],
            "INC-2024-1205",
        ),
        (
            "jan 2025: cart-service lost all carts during redis-cache restart. ~12k active carts gone. product team angry but its the known risk. dynamo backup still not implemented smh",
            ["cart-service", "redis-cache"],
            "INC-2025-0112",
        ),
        (
            "feb 2025: inventory-service p99 went from 2.3s to 8.7s. found a new query path that scanned 14M rows without index. added composite index on (category, warehouse_id). p99 back to 900ms.",
            ["inventory-service", "postgres-primary"],
            "INC-2025-0203",
        ),
        (
            "mar 2025: webhook-service dead letter queue filled up. 50k undelivered webhooks. customer X changed their endpoint URL and didnt tell us. added webhook URL health monitoring.",
            ["webhook-service"],
            "INC-2025-0310",
        ),
        (
            "apr 2025 2am: kafka broker 3 disk full. audit-log topic retention was 90d but nobody checked disk growth. broker went offline, lost 2 hours of audit events. SOC2 finding.",
            ["kafka-events", "audit-service"],
            "INC-2025-0415",
        ),
        (
            "may 2025: ml-model-server GPU OOM during peak reco requests. model too large for p3.2xlarge. switched to model quantization (INT8), latency +20% but fits in memory.",
            ["ml-model-server", "recommendation-service"],
            "INC-2025-0520",
        ),
        (
            "june 2025: CDN cache poisoning. someone invalidated /* on prod cloudfront. took 3hrs to fully re-warm. customers saw slow page loads globally. now invalidation requires approval.",
            ["cdn-service", "cloudfront"],
            "INC-2025-0601",
        ),
        (
            "july 2025: billing-service double-charged 200 customers. race condition in idempotency check during high concurrency. fixed with SELECT FOR UPDATE. refunds issued within 24h.",
            ["billing-service", "postgres-primary"],
            "INC-2025-0715",
        ),
        (
            "aug 2025: config-service polling caused thundering herd. all 200 pods poll every 30s = 400 req/min. added jitter (30s ± 10s random) and etag-based caching. req/min dropped to 50.",
            ["config-service"],
            "INC-2025-0801",
        ),
        (
            "sept 2025: LDAP proxy connection pool exhausted during SSO rush (9am monday). auth-service fell back to DB sessions. 10x slower logins for 20min. increased LDAP pool from 10 to 50.",
            ["auth-service", "ldap-proxy"],
            "INC-2025-0908",
        ),
    ]
    return [
        KnowledgeItem(
            id=f"INC-{src.replace('INC-', '')}",
            content=content,
            knowledge_type="temporal",
            source=f"incident-notes/{src}",
            confidence=0.78,
            related_entities=entities,
            category="synthetic",
            subcategory="incidents",
        )
        for content, entities, src in incidents
    ]


def build_synthetic_policies() -> List[KnowledgeItem]:
    """15 policy/compliance items."""
    policies = [
        (
            "PCI-DSS: payment-gateway and billing-service logs must NOT contain full card numbers, CVV, or cardholder names. Use tokenized references only. Violation = immediate SEV1 + compliance notification within 24h.",
            ["payment-gateway", "billing-service"],
        ),
        (
            "GDPR: user data deletion requests must be processed within 30 days. Pipeline: auth-service → user-db → elasticsearch (remove from search) → S3 (purge backups older than request).",
            ["auth-service", "elasticsearch", "s3"],
        ),
        (
            "SOC2: all production database access must be logged and auditable. Direct psql connections prohibited. Use db-proxy.internal:5432 which records queries to audit-log Kafka topic.",
            ["postgres-primary", "audit-service"],
        ),
        (
            "All production database access requires MFA + VPN + PagerDuty approval. Direct connections blocked by security group. Use bastion: ssh -J bastion.internal psql-proxy.internal.",
            ["postgres-primary", "bastion"],
        ),
        (
            "Secret rotation: all API keys rotated every 90 days via Vault. Services read secrets at startup, never hardcode. Exception: notification-service still uses env vars (migration planned).",
            ["vault", "notification-service"],
        ),
        (
            "Change management: all production changes require peer review + approval in ArgoCD. Emergency changes allowed with post-hoc review within 24h. Rollback authority: on-call engineer.",
            ["argocd"],
        ),
        (
            "SLA: payment-gateway 99.99% uptime (52min downtime/year). order-service 99.95%. All tier-1 services: p99 < 500ms. SLA breach triggers postmortem within 48h.",
            ["payment-gateway", "order-service"],
        ),
        (
            "Data retention: Elasticsearch logs 15 days hot → 30 days warm → delete. S3 archive: 90 days. PostgreSQL backups: 30 days. Kafka audit-log: 90 days retention.",
            ["elasticsearch", "s3", "postgres-primary", "kafka-events"],
        ),
        (
            "Encryption: all data at rest encrypted (AES-256). All inter-service communication via mTLS (Istio). External TLS via cert-manager + Let's Encrypt. Auto-renewal 30 days before expiry.",
            ["istio", "cert-manager"],
        ),
        (
            "Incident response: 1) Page on-call via PagerDuty 2) Open Slack channel #inc-YYYYMMDD-title 3) Assign incident commander 4) Status updates every 15min 5) Postmortem within 48h.",
            ["pagerduty"],
        ),
        (
            "Cost policy: all new services default to ARM/Graviton (r7g) instances. ~20% savings vs x86. Exception: ML workloads needing GPU or x86-specific deps.",
            [],
        ),
        (
            "Deployment: payment-gateway uses blue/green via ArgoCD. Rollback: argocd app rollback payment-gateway (~2min). Canary used for: search-service, recommendation-service.",
            ["payment-gateway", "argocd", "search-service"],
        ),
        (
            "Backup: PostgreSQL hourly WAL archiving + daily full backup to S3. Point-in-time recovery for last 7 days. RPO=1h, RTO=15min.",
            ["postgres-primary", "s3"],
        ),
        (
            "On-call: minimum 2 engineers per rotation. No more than 1 week consecutive. Compensation: $500/week on-call + $200/incident outside business hours.",
            [],
        ),
        (
            "Kubernetes: all new deployments must use Pod Security Standards 'restricted' profile. PodSecurityPolicy deprecated since cluster upgrade to 1.29 (June 2024).",
            [],
        ),
    ]
    return [
        KnowledgeItem(
            id=f"POL-{i:02d}",
            content=content,
            knowledge_type="policy",
            source="compliance/policies",
            confidence=0.95,
            related_entities=entities,
            category="synthetic",
            subcategory="policies",
        )
        for i, (content, entities) in enumerate(policies)
    ]


def build_synthetic_temporal() -> List[KnowledgeItem]:
    """10 items: 5 outdated→current pairs."""
    pairs = [
        # Stripe API version
        (
            "As of Q1 2024, payment-gateway uses Stripe API v2023-12-15. Do NOT upgrade to v2024-01 — breaking change in webhook signature verification.",
            "UPDATE Q3 2024: Stripe API upgraded to v2024-06. The webhook signature issue is fixed. All services should use v2024-06 now. Old HMAC-SHA256 deprecated, use Ed25519.",
            ["payment-gateway", "stripe"],
            "stripe-api",
        ),
        # Kafka migration
        (
            "Self-hosted Kafka cluster at 10.0.1.x. 5 brokers, zookeeper-based. Consumer group for orders: 'order-processors'.",
            "Q1 2024: Migrated from self-hosted Kafka to AWS MSK. Old broker IPs decommissioned. Use MSK endpoint: b-1.msk-prod.abc123.kafka.us-east-1.amazonaws.com:9096. Consumer group renamed to 'order-processing-v2'.",
            ["kafka-events", "msk"],
            "kafka-msk",
        ),
        # K8s upgrade
        (
            "Kubernetes 1.27 cluster. Using PodSecurityPolicy for pod security. PSP manifests in helm charts.",
            "June 2024: K8s upgraded from 1.27 to 1.29. PodSecurityPolicy removed. Replaced with Pod Security Standards. Use 'restricted' profile for all deployments. Old PSP manifests deleted.",
            [],
            "k8s-upgrade",
        ),
        # Monitoring migration
        (
            "Monitoring via Prometheus + Grafana self-hosted. Prometheus at prometheus.internal:9090. Alert rules in prometheus-rules ConfigMap.",
            "Q2 2024: Migrated monitoring to Datadog. Self-hosted Prometheus decommissioned. All alerts now in Datadog monitors. Traces: Datadog APM (10% sampling in prod). Metrics via StatsD on localhost:8125.",
            ["datadog"],
            "monitoring",
        ),
        # Redis upgrade
        (
            "Redis 6.2 with standalone mode. No TLS. Connection: redis-cache.internal:6379.",
            "Q4 2024: Redis upgraded to 7.2 cluster mode with TLS. 3 nodes, 4GB maxmemory each. Requires TLS client cert. Connection: rediss://redis-cache.internal:6380 (note: port changed to 6380 and protocol to rediss://).",
            ["redis-cache"],
            "redis-upgrade",
        ),
    ]

    items = []
    for old, new, entities, name in pairs:
        items.append(
            KnowledgeItem(
                id=f"TMP-{name}-OLD",
                content=old,
                knowledge_type="temporal",
                source=f"engineering-updates/{name}/old",
                confidence=0.65,
                related_entities=entities,
                category="synthetic",
                subcategory="temporal",
            )
        )
        items.append(
            KnowledgeItem(
                id=f"TMP-{name}-NEW",
                content=new,
                knowledge_type="temporal",
                source=f"engineering-updates/{name}/current",
                confidence=0.93,
                related_entities=entities,
                category="synthetic",
                subcategory="temporal",
            )
        )
    return items


def build_synthetic_contradictions() -> List[KnowledgeItem]:
    """15 items: contradiction pairs with known ground truth."""
    contras = [
        # Redis maxmemory
        (
            "Redis session store maxmemory should be 4GB. Higher values cause GC pauses degrading auth-service latency.",
            "Redis session store maxmemory MUST be at least 8GB. The 4GB recommendation is outdated — caused eviction storms during peak login (9-10am EST). Increased after Q2 2024 incident.",
            ["redis-sessions", "auth-service"],
            "redis-mem",
        ),
        # ES refresh interval
        (
            "Elasticsearch refresh_interval can be set to 1s for near-real-time search. Useful for product catalog updates.",
            "Elasticsearch refresh_interval must NEVER be below 5s in production. Setting to 1s caused the 2023 outage by saturating I/O on data nodes.",
            ["elasticsearch", "search-service"],
            "es-refresh",
        ),
        # Health check port
        (
            "payment-gateway health check is on /health port 3000. Readiness probe checks PostgreSQL connectivity.",
            "payment-gateway health check is on /healthz port 8080. The /health on 3000 is the legacy debug endpoint, not used by k8s probes.",
            ["payment-gateway"],
            "health-port",
        ),
        # Connection pool size
        (
            "PostgreSQL connection pool should be set to 100 max. Higher causes connection thrashing.",
            "During peak hours (9-11am EST), PostgreSQL connection pool should be increased to 200. Default 100 is insufficient during load spikes.",
            ["postgres-primary"],
            "pool-size",
        ),
        # Kafka consumer config
        (
            "Kafka max.poll.interval.ms should be default (300000 / 5min). Longer intervals mask consumer health issues.",
            "Kafka max.poll.interval.ms should be 600000 (10min) for order-processing. Default 5min causes unnecessary rebalances during batch processing.",
            ["kafka-events", "order-service"],
            "kafka-poll",
        ),
        # Rollback procedure
        (
            "To rollback a deployment: kubectl rollout undo deployment/<name>. Simple and fast.",
            "Do NOT use kubectl rollout undo. All deployments managed by ArgoCD. Rollback: argocd app rollback <name>. Using kubectl directly breaks ArgoCD sync state.",
            ["argocd"],
            "rollback",
        ),
        # Redis flush
        (
            "If auth-service sessions are causing issues, flush Redis: redis-cli -h redis-sessions FLUSHDB. Warning: logs out all users.",
            "Redis session store should NEVER be flushed in production. FLUSHDB causes cascading auth failures. Instead, increase maxmemory and let LRU eviction handle it.",
            ["redis-sessions", "auth-service"],
            "redis-flush",
        ),
    ]

    items = []
    for a, b, entities, name in contras:
        items.append(
            KnowledgeItem(
                id=f"CONTRA-{name}-A",
                content=a,
                knowledge_type="factual",
                source=f"team-guidelines/{name}",
                confidence=0.80,
                related_entities=entities,
                category="synthetic",
                subcategory="contradictions",
            )
        )
        items.append(
            KnowledgeItem(
                id=f"CONTRA-{name}-B",
                content=b,
                knowledge_type="factual",
                source=f"incident-learnings/{name}",
                confidence=0.90,
                related_entities=entities,
                category="synthetic",
                subcategory="contradictions",
            )
        )
    # One standalone item
    items.append(
        KnowledgeItem(
            id="CONTRA-singleton",
            content="Direct kubectl exec into production pods is allowed for debugging. Use: kubectl exec -it <pod> -- /bin/sh",
            knowledge_type="procedural",
            source="legacy-docs/debugging",
            confidence=0.60,
            related_entities=["payment-gateway"],
            category="synthetic",
            subcategory="contradictions",
        )
    )
    return items


def build_corrections() -> List[Correction]:
    """8 correction pairs."""
    return [
        Correction(
            "COR-01",
            "How do I connect to the production database?",
            "Use psql -h postgres-primary.internal -U admin -d production",
            "Production DB requires MFA + VPN + PagerDuty approval. Use bastion: ssh -J bastion.internal psql-proxy.internal. Direct connections blocked by security groups.",
        ),
        Correction(
            "COR-02",
            "How do I scale payment-gateway?",
            "kubectl scale deployment payment-gateway --replicas=10",
            "Payment-gateway scaling managed by HPA. Do NOT manually scale. Increase HPA maxReplicas in Helm chart and let ArgoCD sync.",
        ),
        Correction(
            "COR-03",
            "How to check Kafka consumer lag?",
            "Use kafka-consumer-groups.sh on kafka-0 broker",
            "Since Q1 2024 migration to MSK, use Datadog: monitor 'kafka.consumer.lag' grouped by consumer_group and topic. Self-hosted kafka-0 no longer exists.",
        ),
        Correction(
            "COR-04",
            "How to rollback a bad deployment?",
            "kubectl rollout undo deployment/payment-gateway",
            "All deployments managed by ArgoCD. Use: argocd app rollback payment-gateway. kubectl rollout undo breaks ArgoCD sync state.",
        ),
        Correction(
            "COR-05",
            "How to debug a payment-gateway pod in production?",
            "kubectl exec -it payment-gateway-abc123 -- /bin/sh",
            "Do NOT kubectl exec into payment-gateway pods — triggers PCI audit alerts. Use debug sidecar: kubectl debug -it payment-gateway-abc123 --image=debug-tools:latest --target=payment",
        ),
        Correction(
            "COR-06",
            "How to invalidate CDN cache?",
            "aws cloudfront create-invalidation --distribution-id E1ABC --paths '/*'",
            "Wildcard invalidation of /* is prohibited after June 2025 incident. Requires approval. For single files: specify exact path. For full purge: request via #devops Slack.",
        ),
        Correction(
            "COR-07",
            "How to flush Redis sessions?",
            "redis-cli -h redis-sessions FLUSHDB",
            "NEVER flush Redis sessions in production. Causes cascading auth failures. Instead, increase maxmemory and wait for LRU eviction. If urgent, page DBA team.",
        ),
        Correction(
            "COR-08",
            "How to rotate API secrets?",
            "Update the environment variable and restart the pod",
            "All secrets managed by Vault with 90-day auto-rotation. Do NOT use env vars. Read secrets from Vault at startup. To trigger early rotation: vault write secret/data/<service>/config rotation_trigger=true",
        ),
    ]


# ═══════════════════════════════════════════════════════════════════
# PHASE 5: BENCHMARK QUERIES
# ═══════════════════════════════════════════════════════════════════

BENCHMARK_QUERIES = [
    # ── Semantic Understanding (8) ────────────────────────────
    BenchmarkQuery(
        "Q01",
        "my kubernetes pods keep restarting and crashing",
        ["crashloopbackoff", "restart", "container"],
        "semantic",
        "Informal symptom → CrashLoopBackOff playbook",
    ),
    BenchmarkQuery(
        "Q02",
        "EC2 instance is very slow and unresponsive",
        ["cpu", "utilization", "cloudwatch"],
        "semantic",
        "Informal → High CPU playbook",
    ),
    BenchmarkQuery(
        "Q03",
        "our app can't connect to the database",
        ["connection", "postgres", "pool"],
        "semantic",
        "Symptom-based → connection pool / RDS playbook",
    ),
    BenchmarkQuery(
        "Q04",
        "emails keep failing to send to customers",
        ["ses", "notification", "bounce"],
        "semantic",
        "Symptom → SES / notification-service",
    ),
    BenchmarkQuery(
        "Q05",
        "kubernetes DNS is broken, services can't find each other",
        ["dns", "coredns", "resolution"],
        "semantic",
        "Symptom → K8s DNS playbook",
    ),
    BenchmarkQuery(
        "Q06",
        "our S3 bucket access is being denied",
        ["s3", "permission", "access", "iam"],
        "semantic",
        "Symptom → S3 access / IAM playbook",
    ),
    BenchmarkQuery(
        "Q07",
        "container keeps getting killed by the system",
        ["oom", "memory", "killed"],
        "semantic",
        "Paraphrase of OOMKilled",
    ),
    BenchmarkQuery(
        "Q08",
        "our load balancer health checks are failing",
        ["health", "check", "target", "load balancer"],
        "semantic",
        "Symptom → ALB/ELB health check playbook",
    ),
    # ── Cross-Entity Reasoning (7) ────────────────────────────
    BenchmarkQuery(
        "Q09",
        "what happens if postgres-primary goes down",
        ["payment", "auth", "order", "down"],
        "cross-entity",
        "Blast radius query",
    ),
    BenchmarkQuery(
        "Q10",
        "what services depend on redis-cache",
        ["cart", "rate-limiter", "search"],
        "cross-entity",
        "Dependency query",
    ),
    BenchmarkQuery(
        "Q11",
        "what infrastructure does payment-gateway need",
        ["postgres", "redis", "kafka", "vault"],
        "cross-entity",
        "Full dependency chain",
    ),
    BenchmarkQuery(
        "Q12",
        "if kafka goes down what breaks",
        ["order", "notification", "analytics", "audit"],
        "cross-entity",
        "Kafka blast radius",
    ),
    BenchmarkQuery(
        "Q13",
        "who owns the notification service and what does it depend on",
        ["kafka", "ses", "redis"],
        "cross-entity",
        "Ownership + dependencies",
    ),
    BenchmarkQuery(
        "Q14",
        "what is the full data deletion pipeline for GDPR",
        ["auth", "elasticsearch", "s3", "30 days"],
        "cross-entity",
        "GDPR pipeline across services",
    ),
    BenchmarkQuery(
        "Q15",
        "what monitoring and observability tools do we use",
        ["datadog", "apm", "traces"],
        "cross-entity",
        "Monitoring stack query",
    ),
    # ── Contradiction-Aware (6) ───────────────────────────────
    BenchmarkQuery(
        "Q16",
        "should I flush redis when auth sessions are high",
        ["redis", "flush", "auth"],
        "contradiction",
        "Contradicting advice about FLUSHDB",
    ),
    BenchmarkQuery(
        "Q17",
        "what is the correct Elasticsearch refresh interval for production",
        ["refresh_interval", "5s"],
        "contradiction",
        "Contradicting 1s vs 5s minimum",
    ),
    BenchmarkQuery(
        "Q18",
        "what port does payment-gateway health check use",
        ["health", "port"],
        "contradiction",
        "Contradicting 8080 vs 3000",
    ),
    BenchmarkQuery(
        "Q19",
        "what should the PostgreSQL connection pool size be",
        ["connection", "pool"],
        "contradiction",
        "Contradicting 100 vs 200",
    ),
    BenchmarkQuery(
        "Q20",
        "how do I rollback a deployment",
        ["argocd", "rollback"],
        "contradiction",
        "kubectl undo vs argocd rollback",
    ),
    BenchmarkQuery(
        "Q21",
        "what is the right max.poll.interval.ms for kafka consumers",
        ["kafka", "poll", "interval"],
        "contradiction",
        "300000 vs 600000",
    ),
    # ── Temporal Reasoning (5) ────────────────────────────────
    BenchmarkQuery(
        "Q22",
        "what Stripe API version should we use for payment-gateway",
        ["stripe", "v2024"],
        "temporal",
        "Should find newer version",
    ),
    BenchmarkQuery(
        "Q23",
        "how do we connect to Kafka brokers",
        ["msk", "kafka"],
        "temporal",
        "Should find MSK migration, not old IPs",
    ),
    BenchmarkQuery(
        "Q24",
        "what monitoring system do we use, Prometheus or Datadog",
        ["datadog"],
        "temporal",
        "Should prefer Datadog (migrated from Prometheus)",
    ),
    BenchmarkQuery(
        "Q25",
        "what Redis version and mode are we running",
        ["redis", "7.2", "cluster"],
        "temporal",
        "Should find Redis 7.2 cluster upgrade",
    ),
    BenchmarkQuery(
        "Q26",
        "do we use PodSecurityPolicy or Pod Security Standards",
        ["pod security standards", "restricted"],
        "temporal",
        "Should find K8s 1.29 upgrade",
    ),
    # ── Compliance/Policy (5) ─────────────────────────────────
    BenchmarkQuery(
        "Q27",
        "can I log credit card numbers for debugging payment issues",
        ["pci", "card", "tokenized"],
        "compliance",
        "PCI-DSS policy",
    ),
    BenchmarkQuery(
        "Q28",
        "I need to access the production database right now for an emergency",
        ["mfa", "vpn", "bastion", "approval"],
        "compliance",
        "DB access policy",
    ),
    BenchmarkQuery(
        "Q29",
        "how long do we have to delete user data when requested",
        ["gdpr", "30 days", "deletion"],
        "compliance",
        "GDPR SLA",
    ),
    BenchmarkQuery(
        "Q30",
        "how often do we rotate API keys and secrets",
        ["vault", "90 days", "rotation"],
        "compliance",
        "Secret rotation policy",
    ),
    BenchmarkQuery(
        "Q31",
        "what is the SLA for payment-gateway uptime",
        ["99.99", "uptime", "payment"],
        "compliance",
        "SLA query",
    ),
    # ── Paraphrased/Indirect (6) ──────────────────────────────
    BenchmarkQuery(
        "Q32",
        "orders are stuck and won't move past pending",
        ["kafka", "consumer", "pending"],
        "paraphrased",
        "Paraphrase of order stuck issue",
    ),
    BenchmarkQuery(
        "Q33",
        "our search results are stale and outdated",
        ["elasticsearch", "refresh", "index"],
        "paraphrased",
        "Stale search → ES refresh interval",
    ),
    BenchmarkQuery(
        "Q34",
        "customers are getting rate limited way too aggressively",
        ["rate-limiter", "redis", "req/s"],
        "paraphrased",
        "Rate limiting issue",
    ),
    BenchmarkQuery(
        "Q35",
        "the shopping cart keeps losing items after some time",
        ["cart", "redis", "ttl"],
        "paraphrased",
        "Cart loss → Redis TTL",
    ),
    BenchmarkQuery(
        "Q36",
        "who do I page for a database problem at 3am",
        ["dba", "oncall", "pagerduty"],
        "paraphrased",
        "Team escalation query",
    ),
    BenchmarkQuery(
        "Q37",
        "how do we handle secret management and API keys",
        ["vault", "rotation", "secret"],
        "paraphrased",
        "Secret management",
    ),
    # ── Multi-Hop Reasoning (8) ───────────────────────────────
    BenchmarkQuery(
        "Q38",
        "payment-gateway returns 503 but PostgreSQL looks healthy",
        ["connection pool", "circuit breaker"],
        "multi-hop",
        "If PG healthy → pool/circuit breaker issue",
    ),
    BenchmarkQuery(
        "Q39",
        "auth-service is slow but not returning errors",
        ["redis", "session", "fallback", "db"],
        "multi-hop",
        "Slow auth → Redis down → DB fallback (10x slower)",
    ),
    BenchmarkQuery(
        "Q40",
        "what happened in the data loss incident last November",
        ["delete", "orders", "backup", "pg_audit"],
        "multi-hop",
        "Should find the accidental DELETE incident",
    ),
    BenchmarkQuery(
        "Q41",
        "notification service is sending duplicate messages how do we fix it",
        ["kafka", "consumer", "rebalance", "idempotency"],
        "multi-hop",
        "Kafka rebalance → duplicate emails incident",
    ),
    BenchmarkQuery(
        "Q42",
        "we need to add a new service what standards do we follow",
        ["graviton", "restricted", "argocd", "vault"],
        "multi-hop",
        "Combining cost/security/deployment policies",
    ),
    BenchmarkQuery(
        "Q43",
        "payment-gateway is down and we need to rollback immediately",
        ["argocd", "rollback", "blue/green"],
        "multi-hop",
        "Emergency rollback procedure",
    ),
    BenchmarkQuery(
        "Q44",
        "audit-service has gaps in the event log what happened",
        ["kafka", "disk", "retention", "soc2"],
        "multi-hop",
        "Kafka disk full → audit gap → SOC2 finding",
    ),
    BenchmarkQuery(
        "Q45",
        "how do I debug a PCI-scoped service in production safely",
        ["debug", "sidecar", "pci", "kubectl"],
        "multi-hop",
        "PCI constraint → use debug sidecar, not exec",
    ),
]


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════


class EnterpriseLoadTest:
    def __init__(self, raptor_url: str):
        self.raptor_url = raptor_url.rstrip("/")
        self.client = httpx.Client(base_url=self.raptor_url, timeout=60.0)
        self.teach_stats = {"created": 0, "duplicate": 0, "merged": 0, "error": 0}
        self.query_results: List[QueryResult] = []

    def run(self, skip_fetch: bool, skip_ingest: bool, max_playbooks: int):
        print("=" * 70)
        print("IncidentFox Self-Learning System — Enterprise Load Test")
        print(f"Target: {self.raptor_url}")
        print("=" * 70)

        # Phase 0: Health
        r = self.client.get("/health")
        if r.status_code != 200:
            print(f"ABORT: Server not healthy ({r.status_code})")
            return False
        print(f"Server healthy, uptime={r.json().get('uptime_seconds', '?'):.0f}s")

        if not skip_ingest:
            # Phase 1: Fetch & parse playbooks
            print(f"\n{'='*70}")
            print("[Phase 1] Fetch & Parse Scoutflo Playbooks")
            print("=" * 70)

            fetcher = PlaybookFetcher()
            raw_pbs = fetcher.fetch_all(force_refresh=not skip_fetch)
            print(f"  Raw playbooks: {len(raw_pbs)}")

            parser = PlaybookParser()
            pb_items = []
            for pb in raw_pbs:
                pb_items.extend(parser.parse(pb["path"], pb["content"]))
            print(f"  Parsed into {len(pb_items)} knowledge items")

            # Breakdown by category
            cats = {}
            for item in pb_items:
                cats[item.category] = cats.get(item.category, 0) + 1
            for cat, count in sorted(cats.items()):
                print(f"    {cat}: {count} items")

            if max_playbooks > 0 and len(pb_items) > max_playbooks:
                pb_items = pb_items[:max_playbooks]
                print(f"  Limited to {max_playbooks} items")

            # Phase 2: Synthetic data
            print(f"\n{'='*70}")
            print("[Phase 2] Generate Synthetic Enterprise Data")
            print("=" * 70)

            syn_services = build_synthetic_services()
            syn_teams = build_synthetic_teams()
            syn_incidents = build_synthetic_incidents()
            syn_policies = build_synthetic_policies()
            syn_temporal = build_synthetic_temporal()
            syn_contras = build_synthetic_contradictions()
            corrections = build_corrections()

            syn_items = (
                syn_services
                + syn_teams
                + syn_incidents
                + syn_policies
                + syn_temporal
                + syn_contras
            )

            print(f"  Service catalog: {len(syn_services)} items")
            print(f"  Team ownership: {len(syn_teams)} items")
            print(f"  Incident history: {len(syn_incidents)} items")
            print(f"  Policies: {len(syn_policies)} items")
            print(f"  Temporal updates: {len(syn_temporal)} items")
            print(f"  Contradictions: {len(syn_contras)} items")
            print(f"  Corrections: {len(corrections)} items")
            print(f"  Total synthetic: {len(syn_items)} items")

            all_items = pb_items + syn_items
            print(f"\n  TOTAL KNOWLEDGE ITEMS: {len(all_items)}")

            # Phase 3: Ingest
            print(f"\n{'='*70}")
            print(f"[Phase 3] Ingesting {len(all_items)} knowledge items")
            print("=" * 70)

            t0 = time.time()
            for i, item in enumerate(all_items):
                if i % 50 == 0:
                    pct = (i / len(all_items)) * 100
                    elapsed = time.time() - t0
                    rate = i / max(elapsed, 0.1)
                    eta = (len(all_items) - i) / max(rate, 0.1)
                    bar_filled = int(30 * pct / 100)
                    bar = f"[{'=' * bar_filled}{' ' * (30 - bar_filled)}]"
                    print(
                        f"\r  {bar} {i}/{len(all_items)} ({pct:.0f}%) "
                        f"| {elapsed:.0f}s elapsed | ~{eta:.0f}s ETA   ",
                        end="",
                        flush=True,
                    )

                self._teach_item(item)

                # Rate limiting: sleep every 20 items
                if (i + 1) % 20 == 0:
                    time.sleep(0.5)

            teach_time = time.time() - t0
            print(
                f"\r  {'[' + '=' * 30 + ']'} {len(all_items)}/{len(all_items)} (100%) "
                f"| {teach_time:.0f}s total                   "
            )
            print(
                f"\n  Results: created={self.teach_stats['created']} "
                f"duplicate={self.teach_stats['duplicate']} "
                f"merged={self.teach_stats['merged']} "
                f"error={self.teach_stats['error']}"
            )
            print(f"  Avg: {teach_time / len(all_items) * 1000:.0f}ms per item")

            # Teach corrections
            print(f"\n  Teaching {len(corrections)} corrections...")
            for corr in corrections:
                r = self.client.post(
                    "/teach/correction",
                    params={
                        "original_query": corr.original_query,
                        "wrong_answer": corr.wrong_answer,
                        "correct_answer": corr.correct_answer,
                    },
                )
                status = (
                    r.json().get("status", "?")
                    if r.status_code == 200
                    else f"err:{r.status_code}"
                )
                print(f"    {corr.id}: {status}")

        # Phase 4: Maintenance
        print(f"\n{'='*70}")
        print("[Phase 4] Maintenance Cycle")
        print("=" * 70)

        r = self.client.post("/maintenance/run")
        if r.status_code == 200:
            data = r.json()
            print(
                f"  Cycle #{data.get('cycle', '?')}: stale={data.get('stale_detected', 0)}, "
                f"gaps={data.get('gaps_detected', 0)}, contradictions={data.get('contradictions_detected', 0)}"
            )

        r = self.client.get("/maintenance/report")
        if r.status_code == 200:
            data = r.json()
            print(f"  Total nodes: {data.get('total_nodes', '?')}")
            print(f"  Active nodes: {data.get('active_nodes', '?')}")

        # Phase 5: Query Benchmark
        print(f"\n{'='*70}")
        print(f"[Phase 5] Query Benchmark — {len(BENCHMARK_QUERIES)} queries")
        print("=" * 70)

        for q in BENCHMARK_QUERIES:
            result = self._run_query(q)
            self.query_results.append(result)

            if result.hit_ratio >= 0.5:
                label = PASS
            elif result.hit_ratio > 0:
                label = WARN
            else:
                label = FAIL

            print(f"\n  {q.id}: [{label}] [{q.category}] {q.description}")
            print(f'      Query: "{q.query}"')
            print(
                f"      Results: {result.num_results} | "
                f"Strategies: {', '.join(result.strategies)} | "
                f"Time: {result.time_ms:.0f}ms"
            )
            print(f"      Found: {result.found_keywords}")
            if result.missing_keywords:
                print(f"      Missing: {result.missing_keywords}")

        # Summary
        self._print_summary()

        overall_rate = self._overall_hit_rate()
        return overall_rate >= 0.70

    def _teach_item(self, item: KnowledgeItem):
        payload = {
            "content": item.content,
            "knowledge_type": item.knowledge_type,
            "source": item.source,
            "confidence": item.confidence,
            "related_entities": item.related_entities,
            "learned_from": "enterprise_load_test",
        }
        try:
            r = self.client.post("/api/v1/teach", json=payload)
            if r.status_code == 200:
                status = r.json().get("status", "unknown")
                if status == "created":
                    self.teach_stats["created"] += 1
                elif status == "duplicate":
                    self.teach_stats["duplicate"] += 1
                else:
                    self.teach_stats["merged"] += 1
            else:
                self.teach_stats["error"] += 1
        except Exception:
            self.teach_stats["error"] += 1

    def _run_query(self, q: BenchmarkQuery) -> QueryResult:
        payload = {"query": q.query, "top_k": 5}
        t0 = time.time()
        r = self.client.post("/query", json=payload)
        query_time = (time.time() - t0) * 1000

        if r.status_code != 200:
            return QueryResult(
                q.id, 0.0, [], q.expect_keywords, 0, [], query_time, q.category
            )

        data = r.json()
        results = data.get("results", [])
        strategies = data.get("strategies_used", [])
        all_text = " ".join(res.get("text", "").lower() for res in results)

        found = [kw for kw in q.expect_keywords if kw.lower() in all_text]
        missing = [kw for kw in q.expect_keywords if kw.lower() not in all_text]
        hit_ratio = len(found) / len(q.expect_keywords) if q.expect_keywords else 0

        return QueryResult(
            q.id,
            hit_ratio,
            found,
            missing,
            len(results),
            strategies,
            query_time,
            q.category,
        )

    def _overall_hit_rate(self) -> float:
        total = len(self.query_results)
        passes = sum(1 for r in self.query_results if r.hit_ratio >= 0.5)
        return passes / total if total else 0

    def _print_summary(self):
        # Per-category metrics
        categories = {}
        for r in self.query_results:
            if r.category not in categories:
                categories[r.category] = []
            categories[r.category].append(r)

        print(f"\n{'='*70}")
        print("ENTERPRISE LOAD TEST RESULTS")
        print("=" * 70)
        print(
            f"\n  {'Category':<22} {'Total':>6} {'Pass':>6} {'Rate':>8} {'Avg Time':>10}"
        )
        print(f"  {'-'*58}")

        for cat in sorted(categories.keys()):
            results = categories[cat]
            total = len(results)
            passes = sum(1 for r in results if r.hit_ratio >= 0.5)
            rate = passes / total * 100
            avg_time = sum(r.time_ms for r in results) / total
            color = (
                "\033[92m" if rate >= 70 else "\033[93m" if rate >= 50 else "\033[91m"
            )
            print(
                f"  {cat:<22} {total:>6} {passes:>6} {color}{rate:>7.0f}%\033[0m {avg_time:>9.0f}ms"
            )

        total = len(self.query_results)
        passes = sum(1 for r in self.query_results if r.hit_ratio >= 0.5)
        partials = sum(1 for r in self.query_results if 0 < r.hit_ratio < 0.5)
        fails = sum(1 for r in self.query_results if r.hit_ratio == 0)
        avg_time = sum(r.time_ms for r in self.query_results) / total
        rate = passes / total * 100

        print(f"  {'-'*58}")
        color = "\033[92m" if rate >= 70 else "\033[91m"
        print(
            f"  {'OVERALL':<22} {total:>6} {passes:>6} {color}{rate:>7.0f}%\033[0m {avg_time:>9.0f}ms"
        )
        print(f"\n  Pass: {passes} | Partial: {partials} | Fail: {fails}")
        print(f"  Avg query time: {avg_time:.0f}ms")
        print("=" * 70)

        if rate >= 70:
            print(f"\n  [{PASS}] Hit rate {rate:.0f}% >= 70% threshold")
        else:
            print(f"\n  [{FAIL}] Hit rate {rate:.0f}% < 70% threshold")


def main():
    parser = argparse.ArgumentParser(description="Enterprise load test for RAG system")
    parser.add_argument("--raptor-url", default="http://localhost:8000")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Use cached playbooks (skip GitHub fetch)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip ingestion (query-only, data must be loaded)",
    )
    parser.add_argument(
        "--max-playbooks", type=int, default=0, help="Limit playbook items (0=all)"
    )
    args = parser.parse_args()

    test = EnterpriseLoadTest(args.raptor_url)
    success = test.run(
        skip_fetch=args.skip_fetch,
        skip_ingest=args.skip_ingest,
        max_playbooks=args.max_playbooks,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
