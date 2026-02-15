#!/usr/bin/env python3
"""
Seed the otel-demo team for AI SRE incident triage demo.

This creates:
1. 'otel-demo' team node under 'incidentfox-demo' org
2. Team configuration with:
   - OTel Demo service catalog (25 microservices)
   - Service dependency map
   - 14 incident scenarios with flagd flag mappings
   - Detection PromQL queries for each scenario
   - Remediation playbook
   - Custom planner prompt for SRE incident triage
3. Output configuration pointing to the Slack channel

Usage:
    cd config_service
    poetry run python scripts/seed_otel_demo.py

Environment variables:
    OTEL_DEMO_SLACK_CHANNEL_ID: Slack channel ID (default from env)
    OTEL_DEMO_SLACK_CHANNEL_NAME: Slack channel name
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import uuid

from sqlalchemy import select
from src.core.dotenv import load_dotenv
from src.db.config_models import NodeConfiguration
from src.db.models import (
    NodeType,
    OrgNode,
    TeamOutputConfig,
)
from src.db.session import db_session

# Configuration
ORG_ID = "incidentfox-demo"
TEAM_NODE_ID = "otel-demo"
TEAM_NAME = "OTel Demo SRE"

# ---------------------------------------------------------------------------
# Service catalog
# ---------------------------------------------------------------------------
SERVICES = {
    "frontend": {
        "language": "TypeScript/Next.js",
        "type": "web-ui",
        "port": 8080,
        "dependencies": [
            "product-catalog",
            "cart",
            "checkout",
            "recommendation",
            "ad",
            "currency",
            "image-provider",
            "product-reviews",
        ],
        "description": "Main web storefront. Renders product pages, cart, and checkout.",
    },
    "frontend-proxy": {
        "language": "Envoy",
        "type": "proxy",
        "port": 8080,
        "dependencies": ["frontend", "grafana", "jaeger"],
        "description": "Envoy reverse proxy for all inbound traffic.",
    },
    "checkout": {
        "language": "Go",
        "type": "backend",
        "port": 8080,
        "dependencies": [
            "cart",
            "payment",
            "shipping",
            "currency",
            "email",
            "product-catalog",
            "kafka",
        ],
        "description": "Orchestrates the checkout flow: validates cart, charges payment, ships order, sends confirmation email, publishes to Kafka.",
    },
    "payment": {
        "language": "Node.js",
        "type": "backend",
        "port": 8080,
        "dependencies": ["flagd"],
        "description": "Processes credit card charges. PRIMARY FAILURE INJECTION TARGET via paymentFailure flag.",
    },
    "cart": {
        "language": "C# (.NET)",
        "type": "backend",
        "port": 8080,
        "dependencies": ["valkey"],
        "description": "Shopping cart backed by Valkey (Redis). Stores cart items per user.",
    },
    "product-catalog": {
        "language": "Go",
        "type": "backend",
        "port": 8080,
        "dependencies": ["flagd"],
        "description": "Lists and searches 12 products. Used by frontend, checkout, recommendation.",
    },
    "recommendation": {
        "language": "Python",
        "type": "backend",
        "port": 8080,
        "dependencies": ["product-catalog", "flagd"],
        "description": "Suggests related products. Has an in-memory cache layer.",
    },
    "shipping": {
        "language": "Rust",
        "type": "backend",
        "port": 8080,
        "dependencies": ["quote"],
        "description": "Calculates shipping quotes and creates shipments.",
    },
    "quote": {
        "language": "PHP",
        "type": "backend",
        "port": 8080,
        "dependencies": [],
        "description": "Calculates shipping cost based on item count.",
    },
    "email": {
        "language": "Ruby",
        "type": "backend",
        "port": 8080,
        "dependencies": ["flagd"],
        "description": "Sends order confirmation emails. Memory leak injection target.",
    },
    "currency": {
        "language": "C++",
        "type": "backend",
        "port": 8080,
        "dependencies": [],
        "description": "Converts prices between currencies.",
    },
    "ad": {
        "language": "Java",
        "type": "backend",
        "port": 8080,
        "dependencies": ["flagd"],
        "description": "Returns contextual ads. CPU spike and GC pressure injection target.",
    },
    "image-provider": {
        "language": "Nginx",
        "type": "static",
        "port": 8080,
        "dependencies": ["flagd"],
        "description": "Serves product images. Latency spike injection target.",
    },
    "product-reviews": {
        "language": "Go",
        "type": "backend",
        "port": 8080,
        "dependencies": ["flagd"],
        "description": "Customer reviews with AI summarization. LLM rate-limit and inaccuracy injection target.",
    },
    "accounting": {
        "language": "C# (.NET)",
        "type": "async-processor",
        "port": 8080,
        "dependencies": ["kafka", "postgres"],
        "description": "Consumes order events from Kafka, records transactions in PostgreSQL.",
    },
    "fraud-detection": {
        "language": "Kotlin",
        "type": "async-processor",
        "port": 8080,
        "dependencies": ["kafka", "flagd"],
        "description": "Consumes order events from Kafka, checks for fraudulent transactions.",
    },
    "load-generator": {
        "language": "Python/Playwright",
        "type": "synthetic",
        "port": None,
        "dependencies": ["frontend", "flagd"],
        "description": "Generates synthetic user traffic. Traffic spike injection target.",
    },
    "flagd": {
        "language": "Go (flagd)",
        "type": "infrastructure",
        "port": 8013,
        "dependencies": [],
        "description": "OpenFeature flag provider. Controls all incident injection scenarios. Reads from ConfigMap, hot-reloads on changes.",
    },
    "kafka": {
        "language": "Apache Kafka",
        "type": "infrastructure",
        "port": 9092,
        "dependencies": [],
        "description": "Message broker for async order processing. Checkout publishes, accounting and fraud-detection consume.",
    },
    "valkey": {
        "language": "Valkey (Redis fork)",
        "type": "infrastructure",
        "port": 6379,
        "dependencies": [],
        "description": "In-memory cache for shopping cart data.",
    },
    "postgres": {
        "language": "PostgreSQL",
        "type": "infrastructure",
        "port": 5432,
        "dependencies": [],
        "description": "Relational database for accounting records.",
    },
    "otel-collector": {
        "language": "OpenTelemetry Collector",
        "type": "observability",
        "port": 4317,
        "dependencies": [],
        "description": "Collects traces, metrics, and logs from all services via OTLP. Exports to Jaeger, Prometheus, OpenSearch, and Coralogix.",
    },
    "prometheus": {
        "language": "Prometheus",
        "type": "observability",
        "port": 9090,
        "dependencies": ["otel-collector"],
        "description": "Time-series metrics storage. Query via PromQL.",
    },
    "jaeger": {
        "language": "Jaeger",
        "type": "observability",
        "port": 16686,
        "dependencies": ["otel-collector"],
        "description": "Distributed tracing backend and UI.",
    },
    "grafana": {
        "language": "Grafana",
        "type": "observability",
        "port": 3000,
        "dependencies": ["prometheus", "jaeger"],
        "description": "Dashboards and visualization for metrics and traces.",
    },
}

# ---------------------------------------------------------------------------
# Service dependency chains (business flows)
# ---------------------------------------------------------------------------
DEPENDENCY_CHAINS = {
    "checkout_flow": {
        "description": "Main business-critical path: user places an order",
        "chain": [
            "Frontend → Checkout Service orchestrates:",
            "  1. GetCart() → Cart → Valkey",
            "  2. GetProducts() → Product Catalog",
            "  3. ConvertCurrency() → Currency Service",
            "  4. GetShippingQuote() → Shipping → Quote Service",
            "  5. ChargeCard() → Payment [FAILURE INJECTION POINT via flagd]",
            "  6. ShipOrder() → Shipping",
            "  7. SendConfirmation() → Email [MEMORY LEAK INJECTION POINT]",
            "  8. EmptyCart() → Cart",
            "  9. PublishOrder() → Kafka → Accounting + Fraud Detection",
        ],
    },
    "product_browse_flow": {
        "description": "User browses products and sees recommendations",
        "chain": [
            "Frontend → Product Catalog (list/search products)",
            "Frontend → Recommendation (suggested products) → Product Catalog",
            "Frontend → Ad Service (contextual ads) [CPU/GC INJECTION POINT]",
            "Frontend → Image Provider (product images) [LATENCY INJECTION POINT]",
            "Frontend → Product Reviews (customer reviews + AI summaries) [LLM INJECTION POINT]",
        ],
    },
    "async_processing_flow": {
        "description": "Asynchronous order processing after checkout",
        "chain": [
            "Checkout → Kafka (publish order event)",
            "Kafka → Accounting (record transaction → PostgreSQL)",
            "Kafka → Fraud Detection (analyze for fraud)",
            "[KAFKA LAG INJECTION POINT via kafkaQueueProblems]",
        ],
    },
}

# ---------------------------------------------------------------------------
# Failure impact map
# ---------------------------------------------------------------------------
FAILURE_IMPACT = {
    "payment": "Checkout fails entirely — no orders created, no emails, no accounting records.",
    "product-catalog": "Complete site outage — affects frontend, recommendations, checkout.",
    "cart": "Cannot add items or view cart. Checkout blocked.",
    "kafka": "Orders process but accounting and fraud detection stop (async, checkout still works).",
    "recommendation": "Product pages load slower, no suggestions shown.",
    "email": "Orders succeed but no confirmation emails sent. Memory leak causes eventual OOM.",
    "ad": "No ads displayed. High CPU may cause cascading latency.",
    "image-provider": "Product images load very slowly (5-10s) or timeout.",
}

# ---------------------------------------------------------------------------
# Incident scenarios with flagd mappings
# ---------------------------------------------------------------------------
INCIDENT_SCENARIOS = {
    "paymentFailure": {
        "name": "Service Failure (Payment)",
        "service": "payment",
        "effect": "Configurable % of payment requests return HTTP 500 errors",
        "variants": {
            "off": 0,
            "10%": 0.1,
            "25%": 0.25,
            "50%": 0.5,
            "75%": 0.75,
            "90%": 0.95,
            "100%": 1,
        },
        "default_active": "50%",
        "detection_promql": 'rate(http_server_request_duration_seconds_count{service_name="payment",http_response_status_code=~"5.."}[5m])',
        "detection_logs": "Search for 'payment' service errors in Coralogix",
        "blast_radius": "Checkout fails entirely — no orders, no emails, no accounting",
        "remediation": "Set paymentFailure flag to 'off'",
    },
    "paymentUnreachable": {
        "name": "Service Unreachable (Payment)",
        "service": "payment",
        "effect": "Payment service becomes completely unreachable (connection refused)",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'up{service_name="payment"}',
        "detection_logs": "Search for 'connection refused' in checkout service logs",
        "blast_radius": "Checkout fails entirely — same as payment failure but with connection errors",
        "remediation": "Set paymentUnreachable flag to 'off'",
    },
    "adHighCpu": {
        "name": "High CPU Load (Ad Service)",
        "service": "ad",
        "effect": "Ad service CPU spikes to 80-100%, latency increases significantly",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'rate(process_cpu_seconds_total{service_name="ad"}[1m])',
        "detection_logs": "Check ad service for slow response times in Coralogix",
        "blast_radius": "Ads not displayed, possible cascading latency on frontend",
        "remediation": "Set adHighCpu flag to 'off'",
    },
    "adManualGc": {
        "name": "GC Pressure (Ad Service)",
        "service": "ad",
        "effect": "Frequent full GC pauses causing latency spikes in ad service",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'rate(jvm_gc_pause_seconds_count{service_name="ad"}[1m])',
        "detection_logs": "Check for GC pause logs in ad service",
        "blast_radius": "Ad service latency spikes during GC pauses",
        "remediation": "Set adManualGc flag to 'off'",
    },
    "adFailure": {
        "name": "Ad Service Failure",
        "service": "ad",
        "effect": "Ad service returns errors for all requests",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'rate(http_server_request_duration_seconds_count{service_name="ad",http_response_status_code=~"5.."}[5m])',
        "detection_logs": "Search for errors in ad service logs",
        "blast_radius": "No ads displayed on frontend",
        "remediation": "Set adFailure flag to 'off'",
    },
    "emailMemoryLeak": {
        "name": "Memory Leak (Email Service)",
        "service": "email",
        "effect": "Gradual memory growth, eventual OOM kill and pod restart",
        "variants": {
            "off": 0,
            "1x": 1,
            "10x": 10,
            "100x": 100,
            "1000x": 1000,
            "10000x": 10000,
        },
        "default_active": "100x",
        "detection_promql": 'process_resident_memory_bytes{service_name="email"}',
        "detection_logs": "Check for OOMKilled events in K8s, rising memory in metrics",
        "blast_radius": "Confirmation emails stop after OOM. Orders still process.",
        "remediation": "Set emailMemoryLeak flag to 'off', then restart the email pod",
    },
    "imageSlowLoad": {
        "name": "Latency Spike (Image Provider)",
        "service": "image-provider",
        "effect": "5-10 second delays added to all image responses",
        "variants": {"off": 0, "5sec": 5000, "10sec": 10000},
        "default_active": "5sec",
        "detection_promql": 'histogram_quantile(0.99, rate(http_server_request_duration_seconds_bucket{service_name="image-provider"}[5m]))',
        "detection_logs": "Check for slow response times on image-provider",
        "blast_radius": "Product pages load very slowly, poor user experience",
        "remediation": "Set imageSlowLoad flag to 'off'",
    },
    "kafkaQueueProblems": {
        "name": "Kafka Queue Problems",
        "service": "kafka/accounting/fraud-detection",
        "effect": "Consumer lag increases, async processing delays grow",
        "variants": {"off": 0, "on": 100},
        "default_active": "on",
        "detection_promql": 'kafka_consumer_lag{topic="orders"}',
        "detection_logs": "Check for consumer lag metrics, delayed processing in accounting/fraud logs",
        "blast_radius": "Orders process but accounting and fraud detection fall behind",
        "remediation": "Set kafkaQueueProblems flag to 'off'",
    },
    "recommendationCacheFailure": {
        "name": "Cache Failure (Recommendation)",
        "service": "recommendation",
        "effect": "Cache misses increase, all requests bypass cache and hit backend",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": "rate(recommendation_cache_miss_total[5m])",
        "detection_logs": "Check recommendation service for cache miss patterns",
        "blast_radius": "Recommendation service latency increases, product-catalog gets more load",
        "remediation": "Set recommendationCacheFailure flag to 'off'",
    },
    "productCatalogFailure": {
        "name": "Product Catalog Failure",
        "service": "product-catalog",
        "effect": "Product queries fail with errors",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'rate(http_server_request_duration_seconds_count{service_name="product-catalog",http_response_status_code=~"5.."}[5m])',
        "detection_logs": "Search for errors in product-catalog logs",
        "blast_radius": "Complete site outage — frontend, recommendations, checkout all break",
        "remediation": "Set productCatalogFailure flag to 'off'",
    },
    "cartFailure": {
        "name": "Cart Service Failure",
        "service": "cart",
        "effect": "Cart operations fail with errors",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'rate(http_server_request_duration_seconds_count{service_name="cart",http_response_status_code=~"5.."}[5m])',
        "detection_logs": "Search for errors in cart service logs",
        "blast_radius": "Cannot add items or view cart, checkout blocked",
        "remediation": "Set cartFailure flag to 'off'",
    },
    "loadGeneratorFloodHomepage": {
        "name": "Traffic Spike",
        "service": "all (via load-generator)",
        "effect": "Massive request flood across all services",
        "variants": {"off": 0, "on": 100},
        "default_active": "on",
        "detection_promql": "sum(rate(http_server_request_duration_seconds_count[1m]))",
        "detection_logs": "Check all services for elevated request rates",
        "blast_radius": "All services may degrade under load",
        "remediation": "Set loadGeneratorFloodHomepage flag to 'off'",
    },
    "llmInaccurateResponse": {
        "name": "LLM Inaccuracy (Product Reviews)",
        "service": "product-reviews",
        "effect": "AI-generated product summaries return incorrect/hallucinated content",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": "",
        "detection_logs": "Check product-reviews responses for data quality issues",
        "blast_radius": "Misleading product information shown to users",
        "remediation": "Set llmInaccurateResponse flag to 'off'",
    },
    "llmRateLimitError": {
        "name": "LLM Rate Limit (Product Reviews)",
        "service": "product-reviews",
        "effect": "Intermittent 429 rate limit errors from LLM provider",
        "variants": {"on": True, "off": False},
        "default_active": "on",
        "detection_promql": 'rate(http_client_request_duration_seconds_count{service_name="product-reviews",http_response_status_code="429"}[5m])',
        "detection_logs": "Search for 429 status codes in product-reviews logs",
        "blast_radius": "Product review AI summaries intermittently fail",
        "remediation": "Set llmRateLimitError flag to 'off'",
    },
}

# ---------------------------------------------------------------------------
# Observability endpoints
# ---------------------------------------------------------------------------
OBSERVABILITY = {
    "coralogix": {
        "url": "https://incidentfox.app.cx498.coralogix.com/",
        "region": "us2",
        "usage": "Primary log and trace analysis. Use Coralogix skills for investigation.",
    },
    "grafana": {
        "url": "http://k8s-oteldemo-grafanap-6f80336927-c3991b69b6e4352a.elb.us-west-2.amazonaws.com/",
        "usage": "Dashboards and Prometheus queries via Grafana API.",
    },
    "github": {
        "repo": "incidentfox/aws-playground",
        "url": "https://github.com/incidentfox/aws-playground",
        "usage": "Source code, deployment correlation, change analysis.",
    },
    "kubernetes": {
        "cluster": "incidentfox-demo",
        "namespace": "otel-demo",
        "usage": "Pod status, events, logs, deployments. Use K8s skills for debugging.",
    },
    "confluence": {
        "url": "https://incidentfox-team.atlassian.net/",
        "usage": "Runbooks, postmortems, service documentation.",
    },
}


# ---------------------------------------------------------------------------
# Build business context for system prompt
# ---------------------------------------------------------------------------
def _build_business_context() -> str:
    lines = []

    # Service catalog
    lines.append("## Service Catalog\n")
    lines.append("| Service | Language | Type | Dependencies |")
    lines.append("|---------|----------|------|--------------|")
    for name, info in SERVICES.items():
        if info["type"] in ("observability", "infrastructure"):
            continue
        deps = ", ".join(info["dependencies"]) if info["dependencies"] else "none"
        lines.append(f"| {name} | {info['language']} | {info['type']} | {deps} |")

    # Dependency chains
    lines.append("\n## Critical Business Flows\n")
    for flow_id, flow in DEPENDENCY_CHAINS.items():
        lines.append(f"### {flow['description']}")
        lines.append("```")
        for step in flow["chain"]:
            lines.append(step)
        lines.append("```\n")

    # Failure impact
    lines.append("## Failure Impact Map\n")
    lines.append("| Service Down | Business Impact |")
    lines.append("|-------------|----------------|")
    for svc, impact in FAILURE_IMPACT.items():
        lines.append(f"| {svc} | {impact} |")

    # Incident scenarios
    lines.append("\n## Incident Scenarios (flagd Feature Flags)\n")
    lines.append(
        "All incidents are controlled by flagd feature flags. To remediate, set the flag to 'off'.\n"
    )
    lines.append("| Flag | Scenario | Service | Detection (PromQL) |")
    lines.append("|------|----------|---------|-------------------|")
    for flag, scenario in INCIDENT_SCENARIOS.items():
        promql = (
            scenario["detection_promql"][:60] + "..."
            if len(scenario["detection_promql"]) > 60
            else scenario["detection_promql"]
        )
        lines.append(
            f"| `{flag}` | {scenario['name']} | {scenario['service']} | `{promql}` |"
        )

    # Observability endpoints
    lines.append("\n## Observability Endpoints\n")
    for name, info in OBSERVABILITY.items():
        url = info.get("url", info.get("repo", ""))
        lines.append(f"- **{name}**: {url}")
        lines.append(f"  {info['usage']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt for OTel Demo SRE planner
# ---------------------------------------------------------------------------
PLANNER_PROMPT = """You are an expert SRE investigator for the OpenTelemetry Demo — a microservices e-commerce application running on Kubernetes (EKS).

## YOUR ENVIRONMENT

You are investigating incidents in a distributed system with 25 microservices written in 8 languages (Go, Node.js, Python, Java, .NET, Rust, PHP, Ruby). All services emit OpenTelemetry traces, metrics, and logs to a central collector.

**Kubernetes cluster**: incidentfox-demo, namespace: otel-demo
**Observability**: Coralogix (logs + traces), Grafana (dashboards + Prometheus metrics)
**Source code**: github.com/incidentfox/aws-playground
**Feature flags**: flagd (controls incident injection via ConfigMap)

## INCIDENT INVESTIGATION METHODOLOGY

### Phase 1: Scope the Problem
- What symptoms are reported? (errors, latency, downtime)
- What services are likely affected? (check the dependency map below)
- When did it start?

### Phase 2: Gather Evidence (Statistics First)
1. **Check active incidents** — Run `list_scenarios.py --active-only` to see if a known scenario is active
2. **Check metrics** — Use Grafana/Prometheus to find error rates, latency spikes
3. **Check logs** — Use Coralogix (statistics first, then sample)
4. **Check K8s** — Pod status, events, restarts

### Phase 3: Correlate & Diagnose
- Cross-reference metrics, logs, and traces
- Follow the dependency chain to find root cause
- Check if the issue is a known flagd-injected scenario

### Phase 4: Remediate
- If the root cause is a feature flag: use `set_flag.py <flag> off --dry-run` then apply
- If the root cause is a pod crash: use remediation scripts to restart
- If the root cause is resource exhaustion: scale the deployment
- Always verify the fix resolved the issue

## KEY PRINCIPLE: FLAGD AWARENESS

Many incidents in this environment are injected via flagd feature flags. When investigating:
1. **Always check active scenarios** as an early step
2. **Correlate the symptoms** with known scenario effects
3. **If a flag matches**: remediate by disabling the flag, then verify
4. **If no flag matches**: investigate as a genuine incident

## TOOLS AT YOUR DISPOSAL

- **Coralogix**: Log statistics, sampling, pattern extraction, trace analysis
- **Kubernetes**: Pod listing, events, logs, deployment status, resource usage
- **Grafana**: Dashboard queries, Prometheus PromQL, alerts
- **GitHub**: Code search, commit history, PR analysis
- **Feature Flags**: List scenarios, get/set flags (via runtime-config-flagd skill)
- **Remediation**: Pod restart, deployment scaling, rollback
- **Confluence**: Runbooks, documentation search

"""


def main() -> None:
    load_dotenv()

    slack_channel_id = os.getenv("OTEL_DEMO_SLACK_CHANNEL_ID", "C0A4967KRBM")
    slack_channel_name = os.getenv("OTEL_DEMO_SLACK_CHANNEL_NAME", "#otel-demo")

    print("Seeding OTel Demo SRE team...")
    print(f"  Organization: {ORG_ID}")
    print(f"  Team: {TEAM_NODE_ID}")
    print(f"  Slack channel: {slack_channel_id} ({slack_channel_name})")

    with db_session() as s:
        # 1. Check that incidentfox-demo org exists
        org = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == ORG_ID,
            )
        ).scalar_one_or_none()

        if org is None:
            print(f"  ERROR: Organization '{ORG_ID}' not found!")
            print("  Please create the organization first or use a different org_id.")
            sys.exit(1)
        else:
            print(f"  Found organization: {org.name}")

        # 2. Create otel-demo team node
        team = s.execute(
            select(OrgNode).where(
                OrgNode.org_id == ORG_ID,
                OrgNode.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team is None:
            print("  Creating otel-demo team...")
            s.add(
                OrgNode(
                    org_id=ORG_ID,
                    node_id=TEAM_NODE_ID,
                    parent_id=ORG_ID,
                    node_type=NodeType.team,
                    name=TEAM_NAME,
                )
            )
        else:
            print("  otel-demo team already exists, updating...")

        s.flush()

        # 3. Build business context
        business_context = _build_business_context()
        full_prompt = PLANNER_PROMPT + "\n" + business_context

        config_json = {
            "team_name": TEAM_NAME,
            "description": "AI SRE for OpenTelemetry Demo — incident triage, diagnosis, and remediation",
            "routing": {
                "slack_channel_ids": [slack_channel_id],
                "github_repos": [],
                "pagerduty_service_ids": [],
                "services": list(SERVICES.keys()),
            },
            "business_context": business_context,
            "service_catalog": SERVICES,
            "dependency_chains": DEPENDENCY_CHAINS,
            "failure_impact": FAILURE_IMPACT,
            "incident_scenarios": INCIDENT_SCENARIOS,
            "observability": OBSERVABILITY,
            "agents": {
                "planner": {
                    "enabled": True,
                    "model": {"name": "gpt-5.2", "temperature": 0.3},
                    "prompt": {
                        "system": full_prompt,
                        "prefix": "",
                        "suffix": "",
                    },
                },
            },
        }

        # 4. Create/update team configuration
        team_cfg = s.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == ORG_ID,
                NodeConfiguration.node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if team_cfg is None:
            print("  Creating team configuration...")
            s.add(
                NodeConfiguration(
                    id=f"cfg-{uuid.uuid4().hex[:12]}",
                    org_id=ORG_ID,
                    node_id=TEAM_NODE_ID,
                    node_type="team",
                    config_json=config_json,
                    updated_by="seed_otel_demo",
                )
            )
        else:
            print("  Updating existing team configuration...")
            team_cfg.config_json = config_json
            team_cfg.updated_by = "seed_otel_demo"

        # 5. Create/update output configuration
        output_cfg = s.execute(
            select(TeamOutputConfig).where(
                TeamOutputConfig.org_id == ORG_ID,
                TeamOutputConfig.team_node_id == TEAM_NODE_ID,
            )
        ).scalar_one_or_none()

        if output_cfg is None:
            print("  Creating output configuration...")
            s.add(
                TeamOutputConfig(
                    org_id=ORG_ID,
                    team_node_id=TEAM_NODE_ID,
                    default_destinations=[
                        {
                            "type": "slack",
                            "channel_id": slack_channel_id,
                            "channel_name": slack_channel_name,
                        }
                    ],
                    trigger_overrides={
                        "slack": "reply_in_thread",
                        "api": "use_default",
                    },
                )
            )
        else:
            print("  Updating existing output configuration...")
            output_cfg.default_destinations = [
                {
                    "type": "slack",
                    "channel_id": slack_channel_id,
                    "channel_name": slack_channel_name,
                }
            ]

        s.commit()

    print("\nOTel Demo SRE seeding complete!")
    print("\n" + "=" * 70)
    print("DEMO SETUP SUMMARY")
    print("=" * 70)
    print(f"\nSlack Channel: {slack_channel_id} ({slack_channel_name})")
    print(f"\nServices: {len(SERVICES)} total")
    app_services = [
        k
        for k, v in SERVICES.items()
        if v["type"] not in ("observability", "infrastructure")
    ]
    print(f"  Application services: {len(app_services)}")
    print(f"  Infrastructure: {len(SERVICES) - len(app_services)}")
    print(f"\nIncident Scenarios: {len(INCIDENT_SCENARIOS)}")
    for flag, scenario in INCIDENT_SCENARIOS.items():
        print(f"  - {flag}: {scenario['name']} ({scenario['service']})")
    print("\nObservability:")
    for name, info in OBSERVABILITY.items():
        print(f"  - {name}: {info.get('url', info.get('repo', ''))}")
    print("\n" + "=" * 70)
    print("\nNext steps:")
    print("  1. Deploy the updated agent with runtime-config-flagd skill")
    print("  2. Route the #otel-demo Slack channel to this team")
    print("  3. Configure integrations (Coralogix, Grafana, K8s) in the admin UI")
    print("  4. Test with: '@bot investigate payment service errors'")
    print("  5. Trigger an incident: trigger-incident.sh service-failure")


if __name__ == "__main__":
    main()
