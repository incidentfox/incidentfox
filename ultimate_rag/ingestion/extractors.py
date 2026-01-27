"""
Extractors for Ultimate RAG.

Specialized extractors for:
- Entity extraction (NER)
- Relationship extraction
- Metadata extraction
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ..graph.entities import Entity, EntityType
    from ..graph.relationships import Relationship, RelationshipType

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """An entity extracted from text."""

    name: str
    entity_type: str
    confidence: float
    span: Tuple[int, int]  # Character positions
    context: str  # Surrounding text
    attributes: Dict[str, Any]


@dataclass
class ExtractedRelationship:
    """A relationship extracted from text."""

    source_entity: str
    target_entity: str
    relationship_type: str
    confidence: float
    evidence: str  # Text that supports this relationship


class EntityExtractor(ABC):
    """Base class for entity extractors."""

    @abstractmethod
    def extract(self, text: str) -> List[ExtractedEntity]:
        """Extract entities from text."""
        pass


class PatternEntityExtractor(EntityExtractor):
    """
    Pattern-based entity extractor.

    Uses regex patterns to find entities. Fast and interpretable,
    but less flexible than ML-based approaches.
    """

    def __init__(self):
        # Define patterns for different entity types
        self.patterns = {
            "service": [
                r"\b([a-z]+-service)\b",
                r"\b([a-z]+-api)\b",
                r"\b([a-z]+-worker)\b",
                r"\b([a-z]+-db)\b",
            ],
            "team": [
                r"\b(team [a-z]+)\b",
                r"\b([a-z]+ team)\b",
                r"\b(platform team)\b",
                r"\b(sre team)\b",
            ],
            "person": [
                r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b",  # Full names
                r"@(\w+)\b",  # Mentions
            ],
            "technology": [
                r"\b(kubernetes|k8s)\b",
                r"\b(docker)\b",
                r"\b(aws|gcp|azure)\b",
                r"\b(postgres(?:ql)?|mysql|mongodb)\b",
                r"\b(redis|memcached)\b",
                r"\b(kafka|rabbitmq)\b",
                r"\b(elasticsearch|opensearch)\b",
            ],
            "endpoint": [
                r"(?:GET|POST|PUT|DELETE|PATCH)\s+(/[\w/{}]+)",
                r"https?://[\w./-]+",
            ],
            "metric": [
                r"\b(\w+_(?:count|total|duration|rate|latency|errors?))\b",
            ],
        }

    def extract(self, text: str) -> List[ExtractedEntity]:
        """Extract entities using patterns."""
        entities = []
        text_lower = text.lower()

        for entity_type, patterns in self.patterns.items():
            for pattern in patterns:
                flags = (
                    re.IGNORECASE if entity_type in ["technology", "endpoint"] else 0
                )

                for match in re.finditer(pattern, text if flags else text_lower, flags):
                    name = match.group(1) if match.lastindex else match.group(0)

                    # Get context (50 chars around match)
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    context = text[start:end]

                    entity = ExtractedEntity(
                        name=name,
                        entity_type=entity_type,
                        confidence=0.8,  # Pattern matches are fairly reliable
                        span=(match.start(), match.end()),
                        context=context,
                        attributes={},
                    )
                    entities.append(entity)

        # Deduplicate by name
        seen = set()
        unique_entities = []
        for entity in entities:
            key = (entity.name.lower(), entity.entity_type)
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)

        return unique_entities


class LLMEntityExtractor(EntityExtractor):
    """
    LLM-based entity extractor.

    Uses a language model for more flexible entity extraction.
    Better at handling variations and context.
    """

    def __init__(self, llm: Any):
        self.llm = llm
        self.prompt_template = """
Extract entities from the following text. For each entity, provide:
- name: The entity name
- type: One of (service, team, person, technology, endpoint, metric)
- attributes: Any relevant attributes

Text:
{text}

Return as JSON array.
"""

    def extract(self, text: str) -> List[ExtractedEntity]:
        """Extract entities using LLM."""
        # Would call LLM here
        # response = self.llm.generate(self.prompt_template.format(text=text))
        # return self._parse_response(response)
        return []


class RelationshipExtractor(ABC):
    """Base class for relationship extractors."""

    @abstractmethod
    def extract(
        self,
        text: str,
        entities: List[ExtractedEntity],
    ) -> List[ExtractedRelationship]:
        """Extract relationships between entities."""
        pass


class PatternRelationshipExtractor(RelationshipExtractor):
    """
    Pattern-based relationship extractor.

    Uses linguistic patterns to find relationships between entities.
    """

    def __init__(self):
        # Define relationship patterns
        # Format: (pattern, source_group, target_group, relationship_type)
        self.patterns = [
            # Dependency patterns
            (r"(\S+)\s+depends\s+on\s+(\S+)", 1, 2, "depends_on"),
            (r"(\S+)\s+requires\s+(\S+)", 1, 2, "depends_on"),
            (r"(\S+)\s+needs\s+(\S+)", 1, 2, "depends_on"),
            # Communication patterns
            (r"(\S+)\s+calls\s+(\S+)", 1, 2, "calls"),
            (r"(\S+)\s+sends\s+(?:to|messages?)\s+(\S+)", 1, 2, "calls"),
            (r"(\S+)\s+connects\s+to\s+(\S+)", 1, 2, "calls"),
            # Ownership patterns
            (r"(\S+)\s+(?:owns|manages|maintains)\s+(\S+)", 1, 2, "owns"),
            (r"(\S+)\s+is\s+(?:owned|managed|maintained)\s+by\s+(\S+)", 2, 1, "owns"),
            # Team membership
            (
                r"(\S+)\s+(?:is\s+)?(?:on|in|part\s+of)\s+(\S+\s+team)",
                1,
                2,
                "member_of",
            ),
            (r"(\S+)\s+leads?\s+(\S+)", 1, 2, "leads"),
            # Documentation
            (r"(\S+)\s+documents?\s+(\S+)", 1, 2, "documents"),
            (r"(\S+)\s+describes?\s+(\S+)", 1, 2, "documents"),
            # Technology usage
            (r"(\S+)\s+uses\s+(\S+)", 1, 2, "uses"),
            (r"(\S+)\s+(?:runs|is\s+built)\s+(?:on|with)\s+(\S+)", 1, 2, "uses"),
        ]

    def extract(
        self,
        text: str,
        entities: List[ExtractedEntity],
    ) -> List[ExtractedRelationship]:
        """Extract relationships using patterns."""
        relationships = []
        text_lower = text.lower()

        # Build entity name set for validation
        entity_names = {e.name.lower() for e in entities}

        for pattern, src_group, tgt_group, rel_type in self.patterns:
            for match in re.finditer(pattern, text_lower):
                source = match.group(src_group)
                target = match.group(tgt_group)

                # Validate entities exist
                source_valid = any(source in name for name in entity_names)
                target_valid = any(target in name for name in entity_names)

                if source_valid or target_valid:
                    # Get evidence (the matched text plus context)
                    start = max(0, match.start() - 20)
                    end = min(len(text), match.end() + 20)
                    evidence = text[start:end]

                    relationship = ExtractedRelationship(
                        source_entity=source,
                        target_entity=target,
                        relationship_type=rel_type,
                        confidence=0.7 if (source_valid and target_valid) else 0.5,
                        evidence=evidence,
                    )
                    relationships.append(relationship)

        return relationships


class MetadataExtractor:
    """
    Extract metadata from documents.

    Infers:
    - Document type (runbook, architecture doc, incident report, etc.)
    - Domain (payments, auth, infrastructure, etc.)
    - Audience (developers, ops, managers)
    - Freshness indicators
    """

    def __init__(self):
        # Document type indicators
        self.type_indicators = {
            "runbook": [
                "runbook",
                "playbook",
                "procedure",
                "step 1",
                "step 2",
                "how to",
            ],
            "incident_report": [
                "incident",
                "postmortem",
                "root cause",
                "timeline",
                "impact",
            ],
            "architecture": [
                "architecture",
                "design doc",
                "system design",
                "components",
                "diagram",
            ],
            "api_doc": ["endpoint", "request", "response", "api", "rest", "graphql"],
            "onboarding": ["getting started", "setup", "installation", "quickstart"],
            "policy": ["policy", "compliance", "must", "required", "prohibited"],
        }

        # Domain indicators
        self.domain_indicators = {
            "payments": [
                "payment",
                "transaction",
                "billing",
                "invoice",
                "stripe",
                "checkout",
            ],
            "auth": [
                "authentication",
                "authorization",
                "oauth",
                "jwt",
                "login",
                "password",
            ],
            "infrastructure": [
                "kubernetes",
                "docker",
                "aws",
                "terraform",
                "deployment",
                "cluster",
            ],
            "data": ["database", "postgres", "mysql", "redis", "cache", "migration"],
            "observability": [
                "monitoring",
                "logging",
                "metrics",
                "tracing",
                "alerts",
                "dashboard",
            ],
        }

        # Audience indicators
        self.audience_indicators = {
            "developer": ["code", "api", "sdk", "library", "function", "class"],
            "ops": ["deploy", "rollback", "scale", "incident", "alert", "oncall"],
            "manager": ["summary", "overview", "business", "stakeholder", "timeline"],
        }

    def extract(self, text: str) -> Dict[str, Any]:
        """Extract metadata from text."""
        text_lower = text.lower()

        metadata = {}

        # Detect document type
        doc_type = self._detect_category(text_lower, self.type_indicators)
        if doc_type:
            metadata["document_type"] = doc_type

        # Detect domain
        domain = self._detect_category(text_lower, self.domain_indicators)
        if domain:
            metadata["domain"] = domain

        # Detect audience
        audience = self._detect_category(text_lower, self.audience_indicators)
        if audience:
            metadata["audience"] = audience

        # Extract dates mentioned
        dates = self._extract_dates(text)
        if dates:
            metadata["dates_mentioned"] = dates

        # Detect urgency/priority
        urgency = self._detect_urgency(text_lower)
        if urgency:
            metadata["urgency"] = urgency

        # Detect completeness
        metadata["completeness"] = self._assess_completeness(text, doc_type)

        return metadata

    def _detect_category(
        self,
        text: str,
        indicators: Dict[str, List[str]],
    ) -> Optional[str]:
        """Detect a category based on indicator keywords."""
        scores = {}

        for category, keywords in indicators.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[category] = score

        if scores:
            return max(scores, key=scores.get)
        return None

    def _extract_dates(self, text: str) -> List[str]:
        """Extract date mentions from text."""
        dates = []

        # ISO dates
        iso_pattern = r"\d{4}-\d{2}-\d{2}"
        dates.extend(re.findall(iso_pattern, text))

        # Written dates
        written_pattern = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
        dates.extend(re.findall(written_pattern, text, re.IGNORECASE))

        return dates[:5]  # Return up to 5 dates

    def _detect_urgency(self, text: str) -> Optional[str]:
        """Detect urgency level."""
        if any(
            kw in text
            for kw in ["critical", "urgent", "immediately", "asap", "emergency"]
        ):
            return "critical"
        elif any(kw in text for kw in ["important", "priority", "soon"]):
            return "high"
        elif any(kw in text for kw in ["when possible", "low priority"]):
            return "low"
        return None

    def _assess_completeness(
        self,
        text: str,
        doc_type: Optional[str],
    ) -> float:
        """Assess how complete a document appears to be."""
        score = 1.0

        # Check for TODO/placeholder indicators
        if any(
            marker in text.lower()
            for marker in ["todo", "tbd", "placeholder", "[insert"]
        ):
            score -= 0.3

        # Check for expected sections based on document type
        if doc_type == "runbook":
            expected = ["prerequisites", "steps", "verification"]
            found = sum(1 for exp in expected if exp in text.lower())
            score *= found / len(expected)

        elif doc_type == "incident_report":
            expected = ["summary", "timeline", "root cause", "action items"]
            found = sum(1 for exp in expected if exp in text.lower())
            score *= found / len(expected)

        return max(0.1, score)


class CombinedExtractor:
    """
    Combines multiple extractors for comprehensive extraction.
    """

    def __init__(
        self,
        entity_extractor: Optional[EntityExtractor] = None,
        relationship_extractor: Optional[RelationshipExtractor] = None,
        metadata_extractor: Optional[MetadataExtractor] = None,
    ):
        self.entity_extractor = entity_extractor or PatternEntityExtractor()
        self.relationship_extractor = (
            relationship_extractor or PatternRelationshipExtractor()
        )
        self.metadata_extractor = metadata_extractor or MetadataExtractor()

    def extract_all(
        self,
        text: str,
    ) -> Dict[str, Any]:
        """Extract all information from text."""
        # Extract entities
        entities = self.entity_extractor.extract(text)

        # Extract relationships using found entities
        relationships = self.relationship_extractor.extract(text, entities)

        # Extract metadata
        metadata = self.metadata_extractor.extract(text)

        return {
            "entities": [
                {
                    "name": e.name,
                    "type": e.entity_type,
                    "confidence": e.confidence,
                }
                for e in entities
            ],
            "relationships": [
                {
                    "source": r.source_entity,
                    "target": r.target_entity,
                    "type": r.relationship_type,
                    "confidence": r.confidence,
                }
                for r in relationships
            ],
            "metadata": metadata,
        }
