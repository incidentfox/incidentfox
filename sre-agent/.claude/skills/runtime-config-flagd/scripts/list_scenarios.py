#!/usr/bin/env python3
"""List available incident scenarios and their current status.

Each scenario maps to a flagd feature flag in the OTel Demo.

Usage:
    python list_scenarios.py
    python list_scenarios.py --active-only
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flagd_client import get_all_flags

# Scenario definitions: flag_key -> scenario metadata
SCENARIOS = {
    "paymentFailure": {
        "name": "Service Failure (Payment)",
        "service": "payment (Node.js)",
        "effect": "Configurable % of payment requests return errors",
        "detection": "HTTP 5xx error rate spike on payment service",
        "promql": 'rate(http_server_request_duration_seconds_count{service_name="payment",http_response_status_code=~"5.."}[5m])',
        "remediation": "Set flag to 'off' (variant: off, value: 0)",
    },
    "paymentUnreachable": {
        "name": "Service Unreachable (Payment)",
        "service": "payment (Node.js)",
        "effect": "Payment service becomes completely unreachable",
        "detection": 'up{service_name="payment"} == 0',
        "promql": 'up{service_name="payment"}',
        "remediation": "Set flag to 'off'",
    },
    "adHighCpu": {
        "name": "High CPU Load (Ad Service)",
        "service": "ad (Java)",
        "effect": "CPU spikes to 80-100%, latency increases",
        "detection": "CPU utilization spike, increased response latency",
        "promql": 'rate(process_cpu_seconds_total{service_name="ad"}[1m])',
        "remediation": "Set flag to 'off'",
    },
    "adManualGc": {
        "name": "GC Pressure (Ad Service)",
        "service": "ad (Java)",
        "effect": "Frequent full GC pauses causing latency spikes",
        "detection": "JVM GC pause frequency and duration increase",
        "promql": 'rate(jvm_gc_pause_seconds_count{service_name="ad"}[1m])',
        "remediation": "Set flag to 'off'",
    },
    "adFailure": {
        "name": "Ad Service Failure",
        "service": "ad (Java)",
        "effect": "Ad service returns errors",
        "detection": "Error rate spike on ad service",
        "promql": 'rate(http_server_request_duration_seconds_count{service_name="ad",http_response_status_code=~"5.."}[5m])',
        "remediation": "Set flag to 'off'",
    },
    "emailMemoryLeak": {
        "name": "Memory Leak (Email Service)",
        "service": "email (Ruby)",
        "effect": "Gradual memory growth, eventual OOM kill",
        "detection": "Rising memory usage, pod restarts with OOMKilled",
        "promql": 'process_resident_memory_bytes{service_name="email"}',
        "remediation": "Set flag to 'off', then restart the email pod",
    },
    "imageSlowLoad": {
        "name": "Latency Spike (Image Provider)",
        "service": "image-provider (Nginx)",
        "effect": "5-10 second delays added to image responses",
        "detection": "High p99 latency on image requests",
        "promql": 'histogram_quantile(0.99, rate(http_server_request_duration_seconds_bucket{service_name="image-provider"}[5m]))',
        "remediation": "Set flag to 'off'",
    },
    "kafkaQueueProblems": {
        "name": "Kafka Queue Problems",
        "service": "checkout/accounting/fraud-detection",
        "effect": "Consumer lag increases, async processing delays",
        "detection": "Kafka consumer lag growth",
        "promql": 'kafka_consumer_lag{topic="orders"}',
        "remediation": "Set flag to 'off'",
    },
    "recommendationCacheFailure": {
        "name": "Cache Failure (Recommendation)",
        "service": "recommendation (Python)",
        "effect": "Cache misses increase, all requests hit backend",
        "detection": "Increased latency on recommendation service, cache miss rate",
        "promql": "rate(recommendation_cache_miss_total[5m])",
        "remediation": "Set flag to 'off'",
    },
    "productCatalogFailure": {
        "name": "Product Catalog Failure",
        "service": "product-catalog (Go)",
        "effect": "Specific product queries fail with errors",
        "detection": "Error spans in traces for product-catalog",
        "promql": 'rate(http_server_request_duration_seconds_count{service_name="product-catalog",http_response_status_code=~"5.."}[5m])',
        "remediation": "Set flag to 'off'",
    },
    "cartFailure": {
        "name": "Cart Service Failure",
        "service": "cart (.NET)",
        "effect": "Cart operations fail",
        "detection": "Error rate on cart service",
        "promql": 'rate(http_server_request_duration_seconds_count{service_name="cart",http_response_status_code=~"5.."}[5m])',
        "remediation": "Set flag to 'off'",
    },
    "loadGeneratorFloodHomepage": {
        "name": "Traffic Spike (Load Generator)",
        "service": "All services (via load generator)",
        "effect": "Massive request flood across all services",
        "detection": "Request rate spike across all services",
        "promql": "sum(rate(http_server_request_duration_seconds_count[1m]))",
        "remediation": "Set flag to 'off'",
    },
    "llmInaccurateResponse": {
        "name": "LLM Inaccuracy (Product Reviews)",
        "service": "product-reviews (Go)",
        "effect": "AI-generated product summaries return incorrect content",
        "detection": "Data quality issue - check review content manually",
        "promql": "",
        "remediation": "Set flag to 'off'",
    },
    "llmRateLimitError": {
        "name": "LLM Rate Limit (Product Reviews)",
        "service": "product-reviews (Go)",
        "effect": "Intermittent 429 rate limit errors from LLM",
        "detection": "429 status codes in product-reviews logs",
        "promql": 'rate(http_client_request_duration_seconds_count{service_name="product-reviews",http_response_status_code="429"}[5m])',
        "remediation": "Set flag to 'off'",
    },
}


def _is_flag_active(flag_config: dict) -> bool:
    """Check if a flag is in an active (non-off) state."""
    default = flag_config.get("defaultVariant", "off")
    variants = flag_config.get("variants", {})
    value = variants.get(default, 0)

    if isinstance(value, bool):
        return value is True
    if isinstance(value, (int, float)):
        return value != 0
    return default != "off"


def main():
    parser = argparse.ArgumentParser(description="List incident scenarios")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Only show currently active scenarios",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        flags = get_all_flags()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    results = []
    for flag_key, scenario in SCENARIOS.items():
        flag_config = flags.get(flag_key, {})
        default = flag_config.get("defaultVariant", "off")
        variants = flag_config.get("variants", {})
        current_value = variants.get(default, "?")
        active = _is_flag_active(flag_config)

        entry = {
            "flag": flag_key,
            "active": active,
            "current_variant": default,
            "current_value": current_value,
            "available_variants": list(variants.keys()),
            **scenario,
        }

        if args.active_only and not active:
            continue

        results.append(entry)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("=" * 80)
    print("INCIDENT SCENARIOS (OTel Demo)")
    print("=" * 80)

    active_count = sum(1 for r in results if r["active"])

    for entry in results:
        status = "ACTIVE" if entry["active"] else "inactive"
        print(f"\n  [{status:>8}] {entry['name']}")
        print(
            f"            Flag: {entry['flag']} = {entry['current_variant']} ({entry['current_value']})"
        )
        print(f"            Service: {entry['service']}")
        print(f"            Effect: {entry['effect']}")
        if entry["active"]:
            print(f"            Remediation: {entry['remediation']}")

    print(f"\n{'=' * 80}")
    print(f"Total: {len(results)} scenarios, {active_count} active")
    print("=" * 80)


if __name__ == "__main__":
    main()
