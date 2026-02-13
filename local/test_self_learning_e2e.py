#!/usr/bin/env python3
"""
E2E validation for the IncidentFox self-learning system.

Tests the full loop: teach → query (observations) → maintenance
against a running ultimate_rag server.

Usage:
    # Start the stack first:
    #   cd local && make start-raptor
    #
    # Then run:
    python local/test_self_learning_e2e.py
    python local/test_self_learning_e2e.py --raptor-url http://localhost:8000
"""

import argparse
import sys
import time
import uuid

import httpx

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"


class E2ERunner:
    def __init__(self, raptor_url: str):
        self.raptor_url = raptor_url.rstrip("/")
        self.client = httpx.Client(base_url=self.raptor_url, timeout=30.0)
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            print(f"  [{PASS}] {name}")
            self.passed += 1
        else:
            msg = f"  [{FAIL}] {name}"
            if detail:
                msg += f" — {detail}"
            print(msg)
            self.failed += 1

    def skip(self, name: str, reason: str = ""):
        msg = f"  [{SKIP}] {name}"
        if reason:
            msg += f" — {reason}"
        print(msg)
        self.skipped += 1

    # ── Test Groups ──────────────────────────────────────────────

    def test_health(self):
        print("\n1. Health Check")
        try:
            r = self.client.get("/health")
            self.check("GET /health returns 200", r.status_code == 200)
            data = r.json()
            self.check("status is healthy", data.get("status") == "healthy")
        except httpx.ConnectError:
            self.check(
                "Server reachable", False, f"Cannot connect to {self.raptor_url}"
            )
            return False
        return True

    def test_teach_new_knowledge(self) -> str | None:
        print("\n2. Teach New Knowledge (POST /api/v1/teach)")
        unique = uuid.uuid4().hex[:8]
        content = (
            f"When the payment-service returns HTTP 503 errors, "
            f"check the upstream database connection pool. The default pool size "
            f"is 20 connections and may need to be increased during peak traffic. "
            f"Test ID: {unique}"
        )
        payload = {
            "content": content,
            "knowledge_type": "procedural",
            "source": "e2e_test",
            "confidence": 0.9,
            "related_entities": ["payment-service"],
            "learned_from": "e2e_test",
            "task_context": "Validating self-learning system",
        }
        r = self.client.post("/api/v1/teach", json=payload)
        self.check(
            "POST /api/v1/teach returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code != 200:
            return None

        data = r.json()
        status = data.get("status", "")
        self.check(
            "status is created or merged",
            status in ("created", "merged"),
            f"got status={status}",
        )
        self.check(
            "node_id returned", data.get("node_id") is not None or status == "merged"
        )
        return content

    def test_teach_duplicate(self, content: str):
        print("\n3. Teach Duplicate")
        if not content:
            self.skip("Duplicate detection", "No content from previous test")
            return
        payload = {
            "content": content,
            "knowledge_type": "procedural",
            "source": "e2e_test",
            "confidence": 0.9,
        }
        r = self.client.post("/api/v1/teach", json=payload)
        self.check("POST returns 200", r.status_code == 200)
        if r.status_code == 200:
            data = r.json()
            self.check(
                "status is duplicate or merged",
                data.get("status") in ("duplicate", "merged"),
                f"got status={data.get('status')}",
            )

    def test_teach_correction(self):
        print("\n4. Teach Correction (POST /teach/correction)")
        r = self.client.post(
            "/teach/correction",
            params={
                "original_query": "How do I restart the payment service?",
                "wrong_answer": "Run kubectl delete pod payment-service",
                "correct_answer": "Run kubectl rollout restart deployment/payment-service to avoid downtime",
            },
        )
        self.check(
            "POST /teach/correction returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code == 200:
            data = r.json()
            self.check(
                "status is created or merged",
                data.get("status") in ("created", "merged"),
                f"got status={data.get('status')}",
            )

    def test_query_retrieves_taught_content(self):
        print("\n5. Query Retrieves Taught Content")
        queries = [
            ("payment service 503 errors", "pool"),
            ("How do I restart the payment service?", "rollout"),
        ]
        any_found = False
        for query_text, expected_keyword in queries:
            payload = {"query": query_text, "top_k": 5}
            r = self.client.post("/query", json=payload)
            self.check(
                f"POST /query '{query_text[:40]}' returns 200",
                r.status_code == 200,
                f"got {r.status_code}",
            )
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])
                found = any(
                    expected_keyword.lower() in res.get("text", "").lower()
                    for res in results
                )
                self.check(
                    f"Query returns result containing '{expected_keyword}'",
                    found,
                    f"got {len(results)} results, none contain '{expected_keyword}'"
                    + (
                        f" | strategies: {data.get('strategies_used', [])}"
                        if not found
                        else ""
                    ),
                )
                if found:
                    any_found = True
                    print(f"    -> Top result score: {results[0].get('score', 'N/A')}")
        return any_found

    def test_maintenance_full_cycle(self):
        print("\n6. Maintenance Full Cycle (POST /maintenance/run)")
        r = self.client.post("/maintenance/run")
        self.check(
            "POST /maintenance/run returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code == 200:
            data = r.json()
            self.check("cycle number present", "cycle" in data)
            self.check("completed_at present", "completed_at" in data)

    def test_maintenance_report(self):
        print("\n7. Maintenance Report (GET /maintenance/report)")
        r = self.client.get("/maintenance/report")
        self.check(
            "GET /maintenance/report returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code == 200:
            data = r.json()
            self.check("total_nodes present", "total_nodes" in data)
            self.check("maintenance_runs present", "maintenance_runs" in data)

    def test_maintenance_sub_endpoints(self):
        print("\n8. Maintenance Sub-Endpoints")

        # POST /maintenance/decay
        r = self.client.post(
            "/maintenance/decay",
            json={"half_life_days": 180, "min_weight": 0.1},
        )
        self.check(
            "POST /maintenance/decay returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code == 200:
            data = r.json()
            self.check("nodes_updated in response", "nodes_updated" in data)

        # POST /maintenance/rebalance
        r = self.client.post(
            "/maintenance/rebalance",
            json={"target_cluster_size": 10, "max_tree_depth": 5},
        )
        self.check(
            "POST /maintenance/rebalance returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code == 200:
            data = r.json()
            self.check("clusters_merged in response", "clusters_merged" in data)

        # POST /maintenance/detect-gaps
        r = self.client.post(
            "/maintenance/detect-gaps",
            json={"analyze_query_logs": True, "min_query_count": 1},
        )
        self.check(
            "POST /maintenance/detect-gaps returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )
        if r.status_code == 200:
            data = r.json()
            self.check("gaps key in response", "gaps" in data)

    def test_maintenance_gaps(self):
        print("\n9. Knowledge Gaps (GET /maintenance/gaps)")
        r = self.client.get("/maintenance/gaps")
        self.check(
            "GET /maintenance/gaps returns 200",
            r.status_code == 200,
            f"got {r.status_code}: {r.text[:200]}",
        )

    # ── Runner ───────────────────────────────────────────────────

    def run_all(self) -> bool:
        print("=" * 60)
        print("IncidentFox Self-Learning System — E2E Validation")
        print(f"Target: {self.raptor_url}")
        print("=" * 60)

        # Health check first — abort if server unreachable
        if not self.test_health():
            print(f"\nServer not reachable at {self.raptor_url}. Aborting.")
            return False

        # Teaching flow
        content = self.test_teach_new_knowledge()
        self.test_teach_duplicate(content)
        self.test_teach_correction()

        # Query — verify retrieval of taught content
        self.test_query_retrieves_taught_content()

        # Maintenance
        self.test_maintenance_full_cycle()
        self.test_maintenance_report()
        self.test_maintenance_sub_endpoints()
        self.test_maintenance_gaps()

        # Summary
        total = self.passed + self.failed + self.skipped
        print("\n" + "=" * 60)
        print(
            f"Results: {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped"
        )
        print("=" * 60)

        return self.failed == 0


def main():
    parser = argparse.ArgumentParser(description="E2E test for self-learning system")
    parser.add_argument(
        "--raptor-url",
        default="http://localhost:8000",
        help="Ultimate RAG server URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    runner = E2ERunner(args.raptor_url)
    success = runner.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
