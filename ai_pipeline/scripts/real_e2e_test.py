#!/usr/bin/env python3
"""
Real E2E test of the onboarding scan system.

Runs against LIVE services:
- Slack API (real workspace)
- GitHub API (real incidentfox/aws-playground repo)
- OpenAI API (real GPT-4o-mini)
- Config service (port-forwarded from EKS)
- Ultimate RAG (port-forwarded from EKS)

Usage:
    export SLACK_BOT_TOKEN=xoxb-...
    export GITHUB_TOKEN=ghp_...
    export OPENAI_API_KEY=sk-...
    export CONFIG_SERVICE_URL=http://localhost:18080
    export RAPTOR_URL=http://localhost:18000

    python scripts/real_e2e_test.py
"""

import asyncio
import json
import os
import sys
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _log(phase: str, msg: str, **fields):
    payload = {"phase": phase, "message": msg, **fields}
    print(f"\n{'='*60}")
    print(f"[{phase}] {msg}")
    if fields:
        for k, v in fields.items():
            if isinstance(v, str) and len(v) > 200:
                v = v[:200] + "..."
            print(f"  {k}: {v}")
    print(f"{'='*60}")


async def main():
    # --- Config ---
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    github_token = os.environ.get("GITHUB_TOKEN")
    openai_key = os.environ.get("OPENAI_API_KEY")
    config_url = os.environ.get("CONFIG_SERVICE_URL", "http://localhost:18080")
    rag_url = os.environ.get("RAPTOR_URL", "http://localhost:18000")
    org_id = "incidentfox-demo"
    team_node_id = "otel-demo"

    assert slack_token, "SLACK_BOT_TOKEN required"
    assert github_token, "GITHUB_TOKEN required"
    assert openai_key, "OPENAI_API_KEY required"

    _log(
        "SETUP",
        "Starting real E2E test",
        org_id=org_id,
        team_node_id=team_node_id,
        config_url=config_url,
        rag_url=rag_url,
    )

    # =========================================================
    # PHASE 1: Slack Scan (real Slack API)
    # =========================================================
    _log("PHASE 1", "Scanning real Slack workspace...")

    from ai_learning_pipeline.tasks.scanners.slack_scanner import (
        SlackEnvironmentScanner,
    )

    scanner = SlackEnvironmentScanner(
        bot_token=slack_token,
        lookback_days=30,
        max_channels=15,
        max_messages_per_channel=100,
    )

    start = time.time()
    scan_result = scanner.scan()
    scan_time = time.time() - start

    _log(
        "PHASE 1 RESULT",
        "Slack scan completed",
        channels_scanned=scan_result.channels_scanned,
        messages_scanned=scan_result.messages_scanned,
        signals_found=len(scan_result.signals),
        messages_collected_for_rag=len(scan_result.collected_messages),
        scan_duration_sec=f"{scan_time:.1f}",
        error=scan_result.error or "None",
    )

    if scan_result.signals:
        print("\n  Signals discovered:")
        for s in scan_result.signals:
            print(
                f"    - {s.integration_id} ({s.signal_type}) "
                f"confidence={s.confidence} "
                f"occurrences={s.metadata.get('occurrence_count', 1)} "
                f"source={s.source}"
            )
            if s.context:
                print(f"      context: {s.context[:120]}...")

    if scan_result.collected_messages:
        channels = set(m.channel_name for m in scan_result.collected_messages)
        print(f"\n  Messages collected from channels: {channels}")

    # =========================================================
    # PHASE 2: Signal Analysis (real OpenAI)
    # =========================================================
    _log("PHASE 2", "Analyzing signals with GPT-4o-mini...")

    from ai_learning_pipeline.tasks.onboarding_scan import SignalAnalyzer

    analyzer = SignalAnalyzer(model="gpt-4o-mini")

    # Get existing integrations from observability config
    existing = ["slack"]  # Slack is always there

    start = time.time()
    analysis = await analyzer.analyze(
        signals=scan_result.signals,
        existing_integrations=existing,
    )
    analysis_time = time.time() - start

    _log(
        "PHASE 2 RESULT",
        "Signal analysis completed",
        recommendations=len(analysis.recommendations),
        analysis_duration_sec=f"{analysis_time:.1f}",
    )

    if analysis.recommendations:
        print("\n  Recommendations:")
        for r in analysis.recommendations:
            print(
                f"    - {r.integration_id}: priority={r.priority} "
                f"confidence={r.confidence}"
            )
            print(f"      reasoning: {r.reasoning[:200]}")
            if r.evidence_quotes:
                print(f"      evidence: {r.evidence_quotes[0][:120]}...")

    if analysis.raw_response:
        print("\n  Raw LLM response (first 500 chars):")
        print(f"    {analysis.raw_response[:500]}")

    # =========================================================
    # PHASE 3: Submit Recommendations (real config service)
    # =========================================================
    _log("PHASE 3", "Submitting recommendations to config service...")

    from ai_learning_pipeline.tasks.onboarding_scan import IntegrationRecommender

    recommender = IntegrationRecommender(config_url)

    start = time.time()
    change_ids = await recommender.submit_recommendations(
        org_id=org_id,
        team_node_id=team_node_id,
        recommendations=analysis.recommendations,
    )
    submit_time = time.time() - start

    _log(
        "PHASE 3 RESULT",
        "Recommendations submitted",
        change_ids_created=len(change_ids),
        change_ids=change_ids,
        submit_duration_sec=f"{submit_time:.1f}",
    )

    # =========================================================
    # PHASE 4: Ingest Slack Knowledge into RAG
    # =========================================================
    _log("PHASE 4", "Ingesting Slack messages into RAG...")

    from collections import defaultdict
    from datetime import datetime

    import httpx
    from ai_learning_pipeline.tasks.onboarding_scan import OnboardingScanTask

    # Build documents from collected messages
    by_channel = defaultdict(list)
    for msg in scan_result.collected_messages:
        by_channel[msg.channel_name].append(msg)

    slack_documents = []
    for channel_name, ch_messages in by_channel.items():
        ch_messages.sort(key=lambda m: m.ts)
        lines = []
        participants = set()
        for msg in ch_messages:
            ts_float = float(msg.ts) if msg.ts else 0
            ts_str = (
                datetime.fromtimestamp(ts_float).strftime("%Y-%m-%d %H:%M")
                if ts_float
                else "unknown"
            )
            lines.append(f"[{ts_str}] {msg.user}: {msg.text}")
            participants.add(msg.user)

        content = "\n".join(lines)
        if len(content) < 100:
            continue

        slack_documents.append(
            {
                "content": content,
                "source_url": f"slack://#{channel_name}",
                "content_type": "slack_thread",
                "metadata": {
                    "channel": channel_name,
                    "message_count": len(ch_messages),
                    "participants": list(participants),
                    "org_id": org_id,
                    "source": "onboarding_scan",
                },
            }
        )

    slack_ingest_result = None
    if slack_documents:
        payload = {
            "documents": slack_documents,
        }

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{rag_url}/ingest/batch",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                slack_ingest_result = (
                    response.json()
                    if response.status_code == 200
                    else {
                        "error": f"HTTP {response.status_code}: {response.text[:200]}"
                    }
                )
        except Exception as e:
            slack_ingest_result = {"error": str(e)}
        ingest_time = time.time() - start

        _log(
            "PHASE 4 RESULT",
            "Slack knowledge ingested into RAG",
            documents_sent=len(slack_documents),
            result=json.dumps(slack_ingest_result, default=str)[:300],
            ingest_duration_sec=f"{ingest_time:.1f}",
        )
    else:
        _log("PHASE 4 RESULT", "No Slack messages to ingest (0 documents)")

    # =========================================================
    # PHASE 5: GitHub Scan (real GitHub API + real OpenAI)
    # =========================================================
    _log("PHASE 5", "Scanning GitHub repos (incidentfox org)...")

    from ai_learning_pipeline.tasks.scanners.github_scanner import scan as github_scan

    start = time.time()
    github_docs = await github_scan(
        credentials={"api_key": github_token},
        config={"account_login": "incidentfox"},
        org_id=org_id,
    )
    github_time = time.time() - start

    _log(
        "PHASE 5 RESULT",
        "GitHub scan completed",
        documents_found=len(github_docs),
        scan_duration_sec=f"{github_time:.1f}",
    )

    if github_docs:
        print("\n  Documents discovered:")
        for doc in github_docs:
            doc_type = doc.metadata.get("document_type", doc.content_type)
            print(f"    - [{doc_type}] {doc.source_url}")
            print(
                f"      content_type={doc.content_type}, "
                f"size={len(doc.content)} chars"
            )
            if doc.metadata.get("document_type") == "architecture_map":
                print("\n  === ARCHITECTURE MAP (first 1000 chars) ===")
                print(f"  {doc.content[:1000]}")
                print("  === END ===\n")
                # Show raw architecture data
                raw = doc.metadata.get("raw_architecture", {})
                services = raw.get("services", [])
                print(f"  Services detected: {len(services)}")
                for svc in services[:10]:
                    print(
                        f"    - {svc.get('name')}: "
                        f"{svc.get('language', '?')}/{svc.get('framework', '?')} "
                        f"deps={svc.get('dependencies', [])}"
                    )
                infra = raw.get("infrastructure", {})
                if infra:
                    print(f"  Infrastructure: {json.dumps(infra, default=str)[:300]}")

    # =========================================================
    # PHASE 6: Ingest GitHub Knowledge into RAG
    # =========================================================
    _log("PHASE 6", "Ingesting GitHub documents into RAG...")

    github_ingest_result = None
    if github_docs:
        payload = {
            "documents": [
                {
                    "content": doc.content,
                    "source_url": doc.source_url,
                    "content_type": doc.content_type,
                    "metadata": {
                        k: v for k, v in doc.metadata.items() if k != "raw_architecture"
                    },  # Skip large nested dict
                }
                for doc in github_docs
            ],
        }

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{rag_url}/ingest/batch",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                github_ingest_result = (
                    response.json()
                    if response.status_code == 200
                    else {
                        "error": f"HTTP {response.status_code}: {response.text[:200]}"
                    }
                )
        except Exception as e:
            github_ingest_result = {"error": str(e)}
        ingest_time = time.time() - start

        _log(
            "PHASE 6 RESULT",
            "GitHub knowledge ingested into RAG",
            documents_sent=len(github_docs),
            result=json.dumps(github_ingest_result, default=str)[:300],
            ingest_duration_sec=f"{ingest_time:.1f}",
        )
    else:
        _log("PHASE 6 RESULT", "No GitHub docs to ingest")

    # =========================================================
    # PHASE 7: Verify RAG State
    # =========================================================
    _log("PHASE 7", "Verifying RAG ingestion state...")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{rag_url}/health")
            health = response.json()

        _log(
            "PHASE 7 RESULT",
            "RAG health check",
            ingest_count=health.get("stats", {}).get("ingest_count", 0),
            processor_docs=health.get("stats", {})
            .get("processor", {})
            .get("total_documents_processed", 0),
            processor_chunks=health.get("stats", {})
            .get("processor", {})
            .get("total_chunks_created", 0),
        )
    except Exception as e:
        _log("PHASE 7 RESULT", f"RAG health check failed: {e}")

    # =========================================================
    # SUMMARY
    # =========================================================
    print("\n" + "=" * 60)
    print("REAL E2E TEST SUMMARY")
    print("=" * 60)
    print(f"  Slack channels scanned:      {scan_result.channels_scanned}")
    print(f"  Slack messages scanned:       {scan_result.messages_scanned}")
    print(f"  Signals discovered:           {len(scan_result.signals)}")
    integrations_found = set(s.integration_id for s in scan_result.signals)
    print(f"  Integrations detected:        {integrations_found}")
    print(f"  LLM recommendations:          {len(analysis.recommendations)}")
    print(f"  Pending changes created:      {len(change_ids)}")
    print(f"  Slack docs ingested to RAG:   {len(slack_documents)}")
    print(f"  GitHub docs ingested to RAG:  {len(github_docs)}")

    arch_docs = [
        d for d in github_docs if d.metadata.get("document_type") == "architecture_map"
    ]
    if arch_docs:
        raw = arch_docs[0].metadata.get("raw_architecture", {})
        print(f"  Architecture map services:    {len(raw.get('services', []))}")

    print(f"\n  Config service:               {config_url}")
    print(f"  RAG service:                  {rag_url}")
    print(f"  Org / Team:                   {org_id} / {team_node_id}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
