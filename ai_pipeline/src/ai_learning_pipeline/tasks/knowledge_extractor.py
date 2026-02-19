"""
LLM-powered Knowledge Extractor.

Transforms raw scan data (Slack messages, GitHub docs, Confluence pages)
into classified, synthesized knowledge items for RAG ingestion.

Uses gpt-4o-mini following the same pattern as
github_scanner._generate_architecture_summary().
"""

import asyncio
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .scanners import Document
from .scanners.slack_scanner import CollectedMessage


def _log(event: str, **fields) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "knowledge_extractor",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


@dataclass
class ExtractedEntity:
    """An entity discovered during knowledge extraction."""

    name: str
    entity_type: str  # "service", "team", "person", "technology", etc.
    canonical_name: str = ""  # lowercase, normalized

    def __post_init__(self):
        if not self.canonical_name:
            self.canonical_name = self.name.lower().strip().replace(" ", "-")


@dataclass
class KnowledgeItem:
    """A single piece of processed, classified knowledge ready for RAG ingestion."""

    content: str
    knowledge_type: str  # "procedural", "factual", "relational", "temporal", "social"
    title: str
    source_url: str = ""
    entities: List[ExtractedEntity] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# Valid knowledge types from ultimate_rag
VALID_KNOWLEDGE_TYPES = {
    "procedural",
    "factual",
    "relational",
    "temporal",
    "social",
    "contextual",
    "policy",
    "meta",
}


def _build_slack_prompt(channel_name: str, formatted_messages: str) -> str:
    """Build the Slack knowledge extraction prompt.

    Uses string concatenation instead of .format() to avoid issues
    with curly braces in message content.
    """
    return (
        "You are an expert SRE knowledge engineer. You are analyzing "
        "Slack messages from the #" + channel_name + " channel of an "
        "engineering team's workspace.\n\n"
        "Your job is to extract operationally useful knowledge that an AI SRE agent "
        "could use when investigating production incidents. Discard chitchat, social "
        "messages, and anything not related to infrastructure, services, incidents, "
        "deployments, or operations.\n\n"
        "## Messages\n\n"
        + formatted_messages + "\n\n"
        "## Instructions\n\n"
        "Analyze these messages and extract KNOWLEDGE ITEMS. Each item should be a "
        "self-contained piece of operational knowledge synthesized from the conversation.\n\n"
        "Produce FEWER, HIGHER-QUALITY items rather than one per message. Synthesize "
        "related messages into coherent knowledge.\n\n"
        "For each item, provide:\n"
        '- "title": A descriptive title (e.g., "Redis connection pool troubleshooting procedure")\n'
        '- "knowledge_type": One of: procedural, factual, relational, temporal, social\n'
        "  - procedural: How to do things (troubleshooting steps, deployment procedures, runbooks)\n"
        "  - factual: What things are (service descriptions, configurations, tool setups)\n"
        "  - relational: How things connect (service dependencies, team ownership, integration points)\n"
        "  - temporal: What happened when (incidents, outages, deployments, changes)\n"
        "  - social: Who knows what (SMEs, escalation paths, team responsibilities, on-call info)\n"
        '- "content": A well-written summary that captures the operational knowledge.\n'
        "  For PROCEDURAL items, include numbered steps.\n"
        "  For TEMPORAL items, include timestamps and what happened.\n"
        "  For RELATIONAL items, describe service dependencies or team ownership.\n"
        "  For SOCIAL items, identify SMEs, escalation paths, or team responsibilities.\n"
        '- "entities": Array of {"name": "...", "type": "service|team|person|technology|metric|environment"}\n'
        '- "confidence": 0.0-1.0 how confident you are in the classification\n\n'
        "Rules:\n"
        "- Skip messages that are purely social or off-topic\n"
        "- If the channel has NO operational knowledge, return an empty items array\n"
        "- Merge related messages into single items (e.g., a troubleshooting thread -> one PROCEDURAL item)\n"
        "- For incident discussions, extract the resolution steps as a separate PROCEDURAL item\n"
        "- Keep each item's content concise but complete (100-300 words)\n\n"
        "Respond in JSON:\n"
        '{\n'
        '  "items": [\n'
        '    {\n'
        '      "title": "...",\n'
        '      "knowledge_type": "procedural",\n'
        '      "content": "...",\n'
        '      "entities": [{"name": "payment-service", "type": "service"}],\n'
        '      "confidence": 0.85\n'
        '    }\n'
        '  ]\n'
        '}'
    )


def _build_document_prompt(
    source_type: str, source_url: str, metadata_hint: str, content: str
) -> str:
    """Build the document knowledge extraction prompt.

    Uses string concatenation instead of .format() to avoid issues
    with curly braces in document content.
    """
    return (
        "You are an expert SRE knowledge engineer. You are processing "
        "a document from " + source_type + " that was discovered during "
        "an onboarding environment scan.\n\n"
        "Your job is to transform this raw document into structured operational "
        "knowledge that an AI SRE agent can use during incident investigation.\n\n"
        "## Document\n"
        "Source: " + source_url + "\n"
        + (metadata_hint + "\n" if metadata_hint else "")
        + "\n" + content + "\n\n"
        "## Instructions\n\n"
        "Analyze this document and produce a structured knowledge extraction:\n\n"
        '1. "knowledge_type": Classify as one of: procedural, factual, relational, temporal, social, policy\n'
        "   - Runbooks, how-tos, troubleshooting guides, deployment steps -> procedural\n"
        "   - Service descriptions, API docs, architecture, configurations -> factual\n"
        "   - Dependency maps, ownership info, integration points -> relational\n"
        "   - Incident reports, postmortems, change logs, deployment history -> temporal\n"
        "   - Team contacts, escalation paths, on-call info, expertise areas -> social\n"
        "   - SLAs, compliance requirements, security policies -> policy\n\n"
        '2. "title": A descriptive title for this knowledge item\n\n'
        '3. "content": Rewrite the document as a concise, operational summary.\n'
        "   - For PROCEDURAL: Extract clear numbered steps. Include prerequisites, "
        "symptoms that trigger this procedure, and affected services.\n"
        "   - For FACTUAL: Extract key facts: what the service does, tech stack, "
        "critical endpoints, deployment method, key configuration.\n"
        "   - For RELATIONAL: Map out dependencies, ownership, communication paths.\n"
        "   - For TEMPORAL: Extract timeline, root cause, resolution, lessons learned.\n"
        "   - Keep it under 500 words. Remove marketing language, redundant text, TODOs.\n\n"
        '4. "entities": Extract all SRE-relevant entities mentioned.\n'
        '   Array of {"name": "...", "type": "service|team|person|technology|metric|environment"}\n\n'
        '5. "confidence": 0.0-1.0 how confident you are in the classification\n\n'
        '6. "skip": true if this document has no operational value for an SRE agent '
        "(e.g., a template with no content, a deprecated notice, marketing copy)\n\n"
        "Respond in JSON:\n"
        '{\n'
        '  "skip": false,\n'
        '  "title": "...",\n'
        '  "knowledge_type": "factual",\n'
        '  "content": "...",\n'
        '  "entities": [{"name": "user-service", "type": "service"}],\n'
        '  "confidence": 0.9\n'
        '}'
    )


class KnowledgeExtractor:
    """
    LLM-powered extraction that transforms raw scan data
    into classified, synthesized knowledge items.

    Uses gpt-4o-mini following the same pattern as
    github_scanner._generate_architecture_summary().
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("SCANNER_LLM_MODEL", "gpt-4o-mini")
        self._semaphore = asyncio.Semaphore(5)

    async def extract_from_slack(
        self,
        messages: List[CollectedMessage],
        org_id: str,
    ) -> List[KnowledgeItem]:
        """Transform raw Slack messages into synthesized knowledge items.

        Groups messages by channel, then uses LLM to extract operational
        knowledge from each channel's messages. Falls back to raw channel
        documents when LLM is unavailable.
        """
        if not messages:
            return []

        # Group by channel
        by_channel: Dict[str, List[CollectedMessage]] = defaultdict(list)
        for msg in messages:
            by_channel[msg.channel_name].append(msg)

        # Process each channel concurrently
        tasks = []
        for channel_name, ch_messages in by_channel.items():
            tasks.append(
                self._extract_from_channel(channel_name, ch_messages, org_id)
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for result in results:
            if isinstance(result, Exception):
                _log("channel_extraction_failed", error=str(result))
                continue
            items.extend(result)

        _log(
            "slack_extraction_complete",
            channels=len(by_channel),
            raw_messages=len(messages),
            items_extracted=len(items),
        )
        return items

    async def _extract_from_channel(
        self,
        channel_name: str,
        messages: List[CollectedMessage],
        org_id: str,
    ) -> List[KnowledgeItem]:
        """Extract knowledge items from a single channel's messages."""
        # Format messages as text
        sorted_msgs = sorted(messages, key=lambda m: m.ts)
        lines = []
        for msg in sorted_msgs:
            ts_str = msg.ts.split(".")[0] if "." in msg.ts else msg.ts
            lines.append("[%s] %s: %s" % (ts_str, msg.user, msg.text))

        formatted = "\n".join(lines)

        # Truncate to ~80K chars (same limit as architecture map)
        if len(formatted) > 80_000:
            formatted = formatted[:80_000] + "\n\n[... truncated ...]"

        prompt = _build_slack_prompt(channel_name, formatted)

        async with self._semaphore:
            result = await self._call_llm(prompt)

        if not result:
            # LLM unavailable — fall back to raw channel document
            return [self._fallback_channel_item(channel_name, messages, org_id)]

        items = []
        for raw_item in result.get("items", []):
            try:
                item = self._parse_knowledge_item(
                    raw_item,
                    source_url="slack://#%s" % channel_name,
                    extra_metadata={
                        "channel": channel_name,
                        "org_id": org_id,
                        "source": "onboarding_scan",
                        "raw_message_count": len(messages),
                    },
                )
                if item:
                    items.append(item)
            except Exception as e:
                _log(
                    "item_parse_failed",
                    channel=channel_name,
                    error=str(e),
                )
                continue

        # If LLM returned no items, fall back to raw
        if not items:
            return [self._fallback_channel_item(channel_name, messages, org_id)]

        return items

    def _fallback_channel_item(
        self,
        channel_name: str,
        messages: List[CollectedMessage],
        org_id: str,
    ) -> KnowledgeItem:
        """Create a raw fallback knowledge item from channel messages."""
        sorted_msgs = sorted(messages, key=lambda m: m.ts)
        participants = set()
        lines = []
        for msg in sorted_msgs:
            try:
                ts_float = float(msg.ts) if msg.ts else 0
                ts_str = (
                    datetime.fromtimestamp(ts_float).strftime("%Y-%m-%d %H:%M")
                    if ts_float
                    else "unknown"
                )
            except (ValueError, OSError):
                ts_str = msg.ts
            lines.append("[%s] %s: %s" % (ts_str, msg.user, msg.text))
            participants.add(msg.user)

        content = "\n".join(lines)

        return KnowledgeItem(
            content=content,
            knowledge_type="temporal",
            title="Slack activity: #%s" % channel_name,
            source_url="slack://#%s" % channel_name,
            confidence=0.3,
            metadata={
                "channel": channel_name,
                "message_count": len(messages),
                "participants": list(participants),
                "org_id": org_id,
                "source": "onboarding_scan",
                "extraction_fallback": True,
            },
        )

    async def extract_from_documents(
        self,
        documents: List[Document],
        source_type: str,
    ) -> List[KnowledgeItem]:
        """Transform raw documents into classified knowledge items.

        Skips documents already tagged as architecture_map (already LLM-processed).
        Processes up to 5 documents concurrently.
        """
        if not documents:
            return []

        tasks = []
        passthrough_items = []

        for doc in documents:
            # Architecture maps are already LLM-processed — pass through as-is
            if doc.metadata.get("document_type") == "architecture_map":
                passthrough_items.append(
                    KnowledgeItem(
                        content=doc.content,
                        knowledge_type="relational",
                        title="Architecture Map: %s" % doc.metadata.get("org_id", "unknown"),
                        source_url=doc.source_url,
                        confidence=0.9,
                        metadata=doc.metadata,
                    )
                )
                continue

            tasks.append(self._extract_from_document(doc, source_type))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = list(passthrough_items)
        for result in results:
            if isinstance(result, Exception):
                _log("document_extraction_failed", error=str(result))
                continue
            if result:
                items.append(result)

        _log(
            "document_extraction_complete",
            source_type=source_type,
            raw_documents=len(documents),
            items_extracted=len(items),
            passthrough=len(passthrough_items),
        )
        return items

    async def _extract_from_document(
        self,
        doc: Document,
        source_type: str,
    ) -> Optional[KnowledgeItem]:
        """Extract a knowledge item from a single document."""
        # Build metadata hint for the LLM
        hints = []
        if doc.metadata.get("title"):
            hints.append("Title: %s" % doc.metadata["title"])
        if doc.metadata.get("path"):
            hints.append("Path: %s" % doc.metadata["path"])
        if doc.metadata.get("repo"):
            hints.append("Repository: %s" % doc.metadata["repo"])
        if doc.metadata.get("search_query"):
            hints.append("Found via search: %s" % doc.metadata["search_query"])
        metadata_hint = "\n".join(hints) if hints else ""

        # Truncate very large documents
        content = doc.content
        if len(content) > 60_000:
            content = content[:60_000] + "\n\n[... truncated ...]"

        prompt = _build_document_prompt(source_type, doc.source_url, metadata_hint, content)

        async with self._semaphore:
            result = await self._call_llm(prompt)

        if not result:
            # LLM failed — fall back to raw ingestion
            return KnowledgeItem(
                content=doc.content,
                knowledge_type="factual",
                title=doc.metadata.get("title", doc.source_url),
                source_url=doc.source_url,
                confidence=0.3,
                metadata=dict(doc.metadata, extraction_fallback=True),
            )

        if result.get("skip", False):
            _log("document_skipped", source_url=doc.source_url)
            return None

        parsed = self._parse_knowledge_item(
            result,
            source_url=doc.source_url,
            extra_metadata=dict(
                doc.metadata,
                original_content_type=doc.content_type,
            ),
        )

        if not parsed:
            # LLM returned valid JSON but unexpected format — fall back to raw
            return KnowledgeItem(
                content=doc.content,
                knowledge_type="factual",
                title=doc.metadata.get("title", doc.source_url),
                source_url=doc.source_url,
                confidence=0.3,
                metadata=dict(doc.metadata, extraction_fallback=True),
            )

        return parsed

    def _parse_knowledge_item(
        self,
        raw: Dict[str, Any],
        source_url: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[KnowledgeItem]:
        """Parse an LLM response item into a KnowledgeItem."""
        content = raw.get("content", "").strip()
        if not content:
            return None

        knowledge_type = raw.get("knowledge_type", "factual").lower().strip()
        if knowledge_type not in VALID_KNOWLEDGE_TYPES:
            knowledge_type = "factual"

        entities = []
        for e in raw.get("entities", []):
            if isinstance(e, dict) and e.get("name"):
                entities.append(
                    ExtractedEntity(
                        name=e["name"],
                        entity_type=e.get("type", "service"),
                    )
                )

        return KnowledgeItem(
            content=content,
            knowledge_type=knowledge_type,
            title=raw.get("title", "Untitled"),
            source_url=source_url,
            entities=entities,
            confidence=min(1.0, max(0.0, float(raw.get("confidence", 0.5)))),
            metadata=extra_metadata or {},
        )

    async def _call_llm(
        self,
        prompt: str,
        max_tokens: int = 3000,
    ) -> Optional[dict]:
        """Call gpt-4o-mini with JSON output.

        Same pattern as github_scanner._generate_architecture_summary().
        """
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()
            response = await client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            return json.loads(raw)

        except Exception as e:
            _log("llm_call_failed", error=str(e), model=self.model)
            return None
