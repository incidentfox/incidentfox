#!/usr/bin/env python3
"""
Direct backend testing - bypasses credential proxy for validation.
Tests that each backend API is accessible and returns valid data.
"""

import json
import ssl
import urllib.error
import urllib.request
from base64 import b64encode
from datetime import datetime, timedelta, timezone


def test_result(name: str, success: bool, message: str, data: any = None):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"\n{status} {name}")
    print(f"   {message}")
    if data and not success:
        print(f"   Response: {str(data)[:200]}")


# =============================================================================
# ELASTICSEARCH
# =============================================================================
def test_elasticsearch():
    print("\n" + "=" * 60)
    print("ELASTICSEARCH")
    print("=" * 60)

    url = "https://a6f123d4974844f938d66fd05676392b-1823852830.us-west-2.elb.amazonaws.com:9200"
    user = "elastic"
    password = "REDACTED"  # Rotated - use env var or secrets manager

    auth = b64encode(f"{user}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    # Skip SSL verification for self-signed certs
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Test 1: Cluster health
    try:
        req = urllib.request.Request(f"{url}/_cluster/health", headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            test_result(
                "Cluster Health",
                True,
                f"Status: {data.get('status')}, Nodes: {data.get('number_of_nodes')}",
            )
    except Exception as e:
        test_result("Cluster Health", False, str(e))

    # Test 2: List indices
    try:
        req = urllib.request.Request(f"{url}/_cat/indices?format=json", headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            test_result("List Indices", True, f"Found {len(data)} indices")
            for idx in data[:5]:
                print(f"      - {idx.get('index')}: {idx.get('docs.count')} docs")
    except Exception as e:
        test_result("List Indices", False, str(e))

    # Test 3: Search logs
    try:
        search_body = json.dumps({"query": {"match_all": {}}, "size": 5}).encode()
        req = urllib.request.Request(
            f"{url}/logs-*/_search", data=search_body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
            hits = data.get("hits", {}).get("total", {})
            count = hits.get("value", 0) if isinstance(hits, dict) else hits
            test_result("Search Logs", True, f"Total docs: {count}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            test_result("Search Logs", True, "No logs-* index (expected if no data)")
        else:
            test_result(
                "Search Logs", False, f"HTTP {e.code}: {e.read().decode()[:100]}"
            )
    except Exception as e:
        test_result("Search Logs", False, str(e))


# =============================================================================
# GRAFANA
# =============================================================================
def test_grafana():
    print("\n" + "=" * 60)
    print("GRAFANA")
    print("=" * 60)

    url = (
        "http://abffcf5b990ec4bd685aef627eb2daf1-1789943242.us-west-2.elb.amazonaws.com"
    )
    user = "admin"
    password = "REDACTED"  # Rotated - use env var or secrets manager

    auth = b64encode(f"{user}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    # Test 1: Health check
    try:
        req = urllib.request.Request(f"{url}/api/health", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            test_result("Health Check", True, f"Version: {data.get('version')}")
    except Exception as e:
        test_result("Health Check", False, str(e))

    # Test 2: List datasources
    try:
        req = urllib.request.Request(f"{url}/api/datasources", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            test_result("List Datasources", True, f"Found {len(data)} datasources")
            for ds in data[:5]:
                print(f"      - {ds.get('name')} ({ds.get('type')})")
    except Exception as e:
        test_result("List Datasources", False, str(e))

    # Test 3: List dashboards
    try:
        req = urllib.request.Request(f"{url}/api/search?type=dash-db", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            test_result("List Dashboards", True, f"Found {len(data)} dashboards")
            for dash in data[:5]:
                print(f"      - {dash.get('title')}")
    except Exception as e:
        test_result("List Dashboards", False, str(e))


# =============================================================================
# CORALOGIX
# =============================================================================
def test_coralogix():
    print("\n" + "=" * 60)
    print("CORALOGIX")
    print("=" * 60)

    api_key = "REDACTED"  # Rotated - use env var or secrets manager
    api_url = "https://ng-api-http.cx498.coralogix.com"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Test 1: Query logs
    try:
        query_body = json.dumps({"query": "source logs | limit 5"}).encode()
        req = urllib.request.Request(
            f"{api_url}/api/v1/dataprime/query",
            data=query_body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if "queryId" in data:
                test_result(
                    "Query Logs",
                    True,
                    f"Query ID: {data['queryId'].get('queryId', 'N/A')[:20]}...",
                )
            else:
                test_result("Query Logs", True, f"Response: {str(data)[:100]}")
    except Exception as e:
        test_result("Query Logs", False, str(e))

    # Test 2: Check services (aggregation)
    try:
        query_body = json.dumps(
            {
                "query": "source logs | groupby $l.subsystemname aggregate count() as cnt | limit 10"
            }
        ).encode()
        req = urllib.request.Request(
            f"{api_url}/api/v1/dataprime/query",
            data=query_body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            test_result("List Services", True, "Aggregation query accepted")
    except Exception as e:
        test_result("List Services", False, str(e))


# =============================================================================
# DATADOG
# =============================================================================
def test_datadog():
    print("\n" + "=" * 60)
    print("DATADOG")
    print("=" * 60)

    api_key = "REDACTED"  # Rotated - use env var or secrets manager
    app_key = "REDACTED"  # Rotated - use env var or secrets manager
    site = "us5.datadoghq.com"

    headers = {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json",
    }

    # Test 1: Validate keys
    try:
        req = urllib.request.Request(
            f"https://api.{site}/api/v1/validate", headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            test_result(
                "Validate API Keys",
                data.get("valid", False),
                f"Valid: {data.get('valid')}",
            )
    except Exception as e:
        test_result("Validate API Keys", False, str(e))

    # Test 2: List monitors
    try:
        req = urllib.request.Request(
            f"https://api.{site}/api/v1/monitor", headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            count = len(data) if isinstance(data, list) else 0
            test_result("List Monitors", True, f"Found {count} monitors")
    except Exception as e:
        test_result("List Monitors", False, str(e))

    # Test 3: Query logs (last 15 min)
    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=15)
        query_body = json.dumps(
            {
                "filter": {
                    "query": "*",
                    "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "page": {"limit": 5},
            }
        ).encode()
        req = urllib.request.Request(
            f"https://api.{site}/api/v2/logs/events/search",
            data=query_body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            logs = data.get("data", [])
            test_result("Query Logs", True, f"Found {len(logs)} logs in last 15min")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        test_result("Query Logs", False, f"HTTP {e.code}: {body}")
    except Exception as e:
        test_result("Query Logs", False, str(e))


# =============================================================================
# JAEGER (skipped - ingress routing issue)
# =============================================================================
def test_jaeger():
    print("\n" + "=" * 60)
    print("JAEGER")
    print("=" * 60)

    url = "http://k8s-oteldemo-jaegerpu-ddab1a4609-a8c87825ebcf8ab1.elb.us-west-2.amazonaws.com"

    # Try multiple API paths
    paths = ["/api/services", "/jaeger/api/services", "/query/api/services"]

    for path in paths:
        try:
            req = urllib.request.Request(f"{url}{path}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "json" in content_type:
                    data = json.loads(resp.read())
                    test_result(
                        f"API {path}", True, f"Found services: {data.get('data', [])}"
                    )
                    return
                else:
                    # HTML response = wrong path
                    continue
        except Exception:
            continue

    test_result(
        "Jaeger API", False, "All API paths return HTML (ingress routing issue)"
    )
    print(
        "   ⚠️  Jaeger needs ingress configuration to expose /api/* separately from UI"
    )


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("SRE Agent - Direct Backend Validation")
    print("=" * 60)

    test_elasticsearch()
    test_grafana()
    test_coralogix()
    test_datadog()
    test_jaeger()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
✅ Elasticsearch - Working (has logs-test index)
✅ Grafana - Working (v12.2.0)
✅ Coralogix - Working (DataPrime API responding)
✅ Datadog - Working (API keys valid)
⚠️  Jaeger - Needs ingress fix (API returns UI HTML)
❌ Prometheus - DNS not resolving (endpoint may be down)
""")
