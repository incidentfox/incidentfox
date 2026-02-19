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
    # PHASE 4: LLM Knowledge Extraction + Ingest Slack into RAG
    # =========================================================
    _log("PHASE 4", "Extracting knowledge from Slack messages with LLM...")

    import httpx
    from ai_learning_pipeline.tasks.knowledge_extractor import KnowledgeExtractor

    extractor = KnowledgeExtractor()

    slack_knowledge_items = []
    if scan_result.collected_messages:
        start = time.time()
        slack_knowledge_items = await extractor.extract_from_slack(
            messages=scan_result.collected_messages,
            org_id=org_id,
        )
        extract_time = time.time() - start

        _log(
            "PHASE 4a",
            "Slack knowledge extraction completed",
            raw_messages=len(scan_result.collected_messages),
            knowledge_items_extracted=len(slack_knowledge_items),
            extract_duration_sec=f"{extract_time:.1f}",
        )

        if slack_knowledge_items:
            print("\n  Extracted knowledge items:")
            for item in slack_knowledge_items:
                print(
                    f"    - [{item.knowledge_type.upper()}] {item.title} "
                    f"(confidence={item.confidence})"
                )
                entities_str = ", ".join(e.name for e in item.entities[:5])
                if entities_str:
                    print(f"      entities: {entities_str}")
                print(f"      content: {item.content[:150]}...")

        # Ingest extracted knowledge into RAG
        slack_documents = []
        for item in slack_knowledge_items:
            slack_documents.append(
                {
                    "content": item.content,
                    "source_url": item.source_url or f"slack://{org_id}",
                    "content_type": "text",
                    "metadata": {
                        "title": item.title,
                        "knowledge_type": item.knowledge_type,
                        "entities": [
                            {"name": e.name, "type": e.entity_type}
                            for e in item.entities
                        ],
                        "confidence": item.confidence,
                        "org_id": org_id,
                        "source": "onboarding_scan",
                    },
                }
            )

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{rag_url}/ingest/batch",
                    json={"documents": slack_documents, "tree": f"slack_{org_id}"},
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
            "PHASE 4b RESULT",
            "Slack knowledge ingested into RAG",
            documents_sent=len(slack_documents),
            knowledge_types=list(
                set(item.knowledge_type for item in slack_knowledge_items)
            ),
            result=json.dumps(slack_ingest_result, default=str)[:300],
            ingest_duration_sec=f"{ingest_time:.1f}",
        )
    else:
        _log("PHASE 4 RESULT", "No Slack messages to extract (0 messages)")

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
    # PHASE 6: LLM Knowledge Extraction + Ingest GitHub into RAG
    # =========================================================
    _log("PHASE 6", "Extracting knowledge from GitHub docs with LLM...")

    github_ingest_result = None
    github_knowledge_items = []
    if github_docs:
        # Separate architecture maps (already LLM-processed) from regular docs
        arch_docs = [
            d
            for d in github_docs
            if d.metadata.get("document_type") == "architecture_map"
        ]
        regular_docs = [
            d
            for d in github_docs
            if d.metadata.get("document_type") != "architecture_map"
        ]

        start = time.time()
        if regular_docs:
            github_knowledge_items = await extractor.extract_from_documents(
                documents=regular_docs,
                source_type="github",
            )
        extract_time = time.time() - start

        _log(
            "PHASE 6a",
            "GitHub knowledge extraction completed",
            raw_docs=len(regular_docs),
            arch_maps=len(arch_docs),
            knowledge_items_extracted=len(github_knowledge_items),
            extract_duration_sec=f"{extract_time:.1f}",
        )

        if github_knowledge_items:
            print("\n  Extracted GitHub knowledge items:")
            for item in github_knowledge_items:
                print(
                    f"    - [{item.knowledge_type.upper()}] {item.title} "
                    f"(confidence={item.confidence})"
                )
                entities_str = ", ".join(e.name for e in item.entities[:5])
                if entities_str:
                    print(f"      entities: {entities_str}")
                print(f"      content: {item.content[:150]}...")

        # Build documents for ingestion
        github_ingest_docs = []

        # Architecture maps pass through with knowledge_type=relational
        for doc in arch_docs:
            meta = {k: v for k, v in doc.metadata.items() if k != "raw_architecture"}
            meta["knowledge_type"] = "relational"
            github_ingest_docs.append(
                {
                    "content": doc.content,
                    "source_url": doc.source_url,
                    "content_type": doc.content_type,
                    "metadata": meta,
                }
            )

        # Extracted knowledge items
        for item in github_knowledge_items:
            github_ingest_docs.append(
                {
                    "content": item.content,
                    "source_url": item.source_url or "",
                    "content_type": "text",
                    "metadata": {
                        "title": item.title,
                        "knowledge_type": item.knowledge_type,
                        "entities": [
                            {"name": e.name, "type": e.entity_type}
                            for e in item.entities
                        ],
                        "confidence": item.confidence,
                        "org_id": org_id,
                        "source": "integration_scan",
                    },
                }
            )

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{rag_url}/ingest/batch",
                    json={"documents": github_ingest_docs, "tree": f"github_{org_id}"},
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

        all_knowledge_types = ["relational"] * len(arch_docs) + [
            item.knowledge_type for item in github_knowledge_items
        ]

        _log(
            "PHASE 6b RESULT",
            "GitHub knowledge ingested into RAG",
            documents_sent=len(github_ingest_docs),
            knowledge_types=list(set(all_knowledge_types)),
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
    print(f"  Slack channels scanned:       {scan_result.channels_scanned}")
    print(f"  Slack messages scanned:        {scan_result.messages_scanned}")
    print(f"  Signals discovered:            {len(scan_result.signals)}")
    integrations_found = set(s.integration_id for s in scan_result.signals)
    print(f"  Integrations detected:         {integrations_found}")
    print(f"  LLM recommendations:           {len(analysis.recommendations)}")
    print(f"  Pending changes created:       {len(change_ids)}")

    print("\n  --- Knowledge Extraction ---")
    print(f"  Slack knowledge items:         {len(slack_knowledge_items)}")
    slack_kt = (
        set(item.knowledge_type for item in slack_knowledge_items)
        if slack_knowledge_items
        else set()
    )
    print(f"  Slack knowledge types:         {slack_kt or 'none'}")
    print(f"  GitHub knowledge items:        {len(github_knowledge_items)}")
    github_kt = (
        set(item.knowledge_type for item in github_knowledge_items)
        if github_knowledge_items
        else set()
    )
    print(f"  GitHub knowledge types:        {github_kt or 'none'}")

    print("\n  --- RAG Ingestion ---")
    print(
        f"  Slack docs ingested to RAG:    {len(slack_documents) if 'slack_documents' in dir() else 0}"
    )
    print(f"  GitHub docs ingested to RAG:   {len(github_docs)}")

    arch_docs_summary = [
        d for d in github_docs if d.metadata.get("document_type") == "architecture_map"
    ]
    if arch_docs_summary:
        raw = arch_docs_summary[0].metadata.get("raw_architecture", {})
        print(f"  Architecture map services:     {len(raw.get('services', []))}")

    all_types = slack_kt | github_kt
    if arch_docs_summary:
        all_types.add("relational")
    print(f"\n  ALL KNOWLEDGE TYPES INGESTED:  {all_types}")

    print(f"\n  Config service:                {config_url}")
    print(f"  RAG service:                   {rag_url}")
    print(f"  Org / Team:                    {org_id} / {team_node_id}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
