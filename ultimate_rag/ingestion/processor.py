"""
Document Processor for Ultimate RAG.

Handles the full pipeline from raw content to knowledge nodes:
1. Parsing content from various formats
2. Chunking with context preservation
3. Entity and relationship extraction
4. Metadata enrichment
5. Integration with RAPTOR tree building
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

if TYPE_CHECKING:
    from ..core.node import KnowledgeNode, KnowledgeTree
    from ..graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """Supported content types."""

    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"
    PDF = "pdf"
    RUNBOOK = "runbook"
    INCIDENT_REPORT = "incident_report"
    API_DOC = "api_doc"
    SLACK_THREAD = "slack_thread"
    CODE = "code"


@dataclass
class ChunkingConfig:
    """Configuration for text chunking."""

    # Chunk sizes
    target_chunk_size: int = 500  # Target tokens per chunk
    max_chunk_size: int = 1000  # Maximum tokens per chunk
    min_chunk_size: int = 100  # Minimum tokens per chunk
    overlap_size: int = 50  # Overlap between chunks

    # Context preservation
    preserve_sections: bool = True  # Keep section headers with chunks
    preserve_code_blocks: bool = True  # Don't split code blocks
    preserve_lists: bool = True  # Keep list items together

    # Semantic chunking
    use_semantic_chunking: bool = False  # Use embeddings to find boundaries
    semantic_threshold: float = 0.7  # Similarity threshold for boundaries


@dataclass
class ProcessingConfig:
    """Configuration for document processing."""

    # Chunking
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)

    # Entity extraction
    extract_entities: bool = True
    entity_types: List[str] = field(
        default_factory=lambda: ["service", "person", "team", "technology", "endpoint"]
    )

    # Relationship extraction
    extract_relationships: bool = True

    # Metadata
    infer_metadata: bool = True
    require_source: bool = True  # Require source attribution

    # Quality
    deduplicate: bool = True
    min_quality_score: float = 0.3

    # Incremental
    track_changes: bool = True  # Track for incremental updates


@dataclass
class ProcessedChunk:
    """A chunk of processed content."""

    chunk_id: str
    text: str
    content_type: ContentType

    # Position
    source_path: str
    section: Optional[str] = None
    position: int = 0  # Position in document

    # Extracted information
    entities: List[str] = field(default_factory=list)
    relationships: List[Tuple[str, str, str]] = field(
        default_factory=list
    )  # (source, rel, target)
    keywords: List[str] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Quality
    quality_score: float = 1.0
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.md5(self.text.encode()).hexdigest()


@dataclass
class ProcessingResult:
    """Result of document processing."""

    # Chunks
    chunks: List[ProcessedChunk]

    # Statistics
    source_path: str
    content_type: ContentType
    total_characters: int
    total_chunks: int
    processing_time_ms: float

    # Extraction results
    entities_found: List[str]
    relationships_found: List[Tuple[str, str, str]]

    # Issues
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class DocumentProcessor:
    """
    Main processor for ingesting documents into the knowledge base.

    Usage:
        processor = DocumentProcessor(config)

        # Process a single file
        result = processor.process_file("docs/runbook.md")

        # Process multiple files
        results = processor.process_directory("docs/")

        # Get chunks for RAPTOR
        texts = [chunk.text for chunk in result.chunks]
        metadata = [chunk.metadata for chunk in result.chunks]
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()

        # Content hash tracking for deduplication
        self._seen_hashes: Set[str] = set()

        # Stats
        self._total_processed = 0
        self._total_chunks = 0

    def process_file(
        self,
        file_path: Union[str, Path],
        content_type: Optional[ContentType] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """
        Process a single file.

        Args:
            file_path: Path to file
            content_type: Override content type detection
            extra_metadata: Additional metadata to attach

        Returns:
            ProcessingResult with chunks
        """
        start_time = datetime.utcnow()
        file_path = Path(file_path)

        logger.info(f"Processing file: {file_path}")

        # Detect content type
        if content_type is None:
            content_type = self._detect_content_type(file_path)

        # Read content
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return ProcessingResult(
                chunks=[],
                source_path=str(file_path),
                content_type=content_type,
                total_characters=0,
                total_chunks=0,
                processing_time_ms=0,
                entities_found=[],
                relationships_found=[],
                errors=[f"Failed to read file: {e}"],
            )

        # Process content
        result = self.process_content(
            content=content,
            source_path=str(file_path),
            content_type=content_type,
            extra_metadata=extra_metadata,
        )

        end_time = datetime.utcnow()
        result.processing_time_ms = (end_time - start_time).total_seconds() * 1000

        return result

    def process_content(
        self,
        content: str,
        source_path: str,
        content_type: ContentType,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """
        Process raw content.

        Args:
            content: Raw text content
            source_path: Source attribution
            content_type: Type of content
            extra_metadata: Additional metadata

        Returns:
            ProcessingResult with chunks
        """
        warnings = []
        errors = []
        all_entities = []
        all_relationships = []

        # Step 1: Parse content based on type
        parsed = self._parse_content(content, content_type)

        # Step 2: Chunk content
        raw_chunks = self._chunk_content(parsed, content_type)

        # Step 3: Process each chunk
        processed_chunks = []
        for i, (text, section) in enumerate(raw_chunks):
            # Generate chunk ID
            chunk_id = f"{hashlib.md5(source_path.encode()).hexdigest()[:8]}_{i}"

            # Check for duplicates
            content_hash = hashlib.md5(text.encode()).hexdigest()
            if self.config.deduplicate and content_hash in self._seen_hashes:
                continue
            self._seen_hashes.add(content_hash)

            # Extract entities
            entities = []
            if self.config.extract_entities:
                entities = self._extract_entities(text)
                all_entities.extend(entities)

            # Extract relationships
            relationships = []
            if self.config.extract_relationships:
                relationships = self._extract_relationships(text, entities)
                all_relationships.extend(relationships)

            # Extract keywords
            keywords = self._extract_keywords(text)

            # Infer metadata
            metadata = extra_metadata.copy() if extra_metadata else {}
            if self.config.infer_metadata:
                inferred = self._infer_metadata(text, content_type)
                metadata.update(inferred)

            metadata["source_path"] = source_path
            metadata["content_type"] = content_type.value
            metadata["processed_at"] = datetime.utcnow().isoformat()

            # Compute quality score
            quality = self._compute_quality(text)
            if quality < self.config.min_quality_score:
                warnings.append(
                    f"Low quality chunk at position {i}: score={quality:.2f}"
                )
                continue

            # Create chunk
            chunk = ProcessedChunk(
                chunk_id=chunk_id,
                text=text,
                content_type=content_type,
                source_path=source_path,
                section=section,
                position=i,
                entities=entities,
                relationships=relationships,
                keywords=keywords,
                metadata=metadata,
                quality_score=quality,
                content_hash=content_hash,
            )
            processed_chunks.append(chunk)

        self._total_processed += 1
        self._total_chunks += len(processed_chunks)

        return ProcessingResult(
            chunks=processed_chunks,
            source_path=source_path,
            content_type=content_type,
            total_characters=len(content),
            total_chunks=len(processed_chunks),
            processing_time_ms=0,  # Will be set by caller
            entities_found=list(set(all_entities)),
            relationships_found=list(set(all_relationships)),
            warnings=warnings,
            errors=errors,
        )

    def process_directory(
        self,
        directory: Union[str, Path],
        pattern: str = "**/*",
        content_type: Optional[ContentType] = None,
    ) -> List[ProcessingResult]:
        """Process all files in a directory."""
        directory = Path(directory)
        results = []

        for file_path in directory.glob(pattern):
            if file_path.is_file() and not file_path.name.startswith("."):
                try:
                    result = self.process_file(file_path, content_type)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")

        return results

    # ==================== Content Parsing ====================

    def _detect_content_type(self, file_path: Path) -> ContentType:
        """Detect content type from file extension."""
        suffix = file_path.suffix.lower()

        mapping = {
            ".md": ContentType.MARKDOWN,
            ".markdown": ContentType.MARKDOWN,
            ".html": ContentType.HTML,
            ".htm": ContentType.HTML,
            ".txt": ContentType.TEXT,
            ".pdf": ContentType.PDF,
            ".py": ContentType.CODE,
            ".js": ContentType.CODE,
            ".ts": ContentType.CODE,
            ".go": ContentType.CODE,
            ".java": ContentType.CODE,
        }

        return mapping.get(suffix, ContentType.TEXT)

    def _parse_content(
        self,
        content: str,
        content_type: ContentType,
    ) -> str:
        """Parse content based on type."""
        if content_type == ContentType.HTML:
            return self._parse_html(content)
        elif content_type == ContentType.MARKDOWN:
            return self._parse_markdown(content)
        elif content_type == ContentType.RUNBOOK:
            return self._parse_runbook(content)
        else:
            return content

    def _parse_html(self, content: str) -> str:
        """Convert HTML to plain text."""
        try:
            from html.parser import HTMLParser

            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text_parts = []

                def handle_data(self, data):
                    self.text_parts.append(data)

            parser = TextExtractor()
            parser.feed(content)
            return " ".join(parser.text_parts)
        except Exception:
            # Fallback: simple tag removal
            import re

            return re.sub(r"<[^>]+>", "", content)

    def _parse_markdown(self, content: str) -> str:
        """Parse markdown, preserving structure hints."""
        # Keep markdown mostly intact for chunking
        # Just normalize whitespace
        import re

        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _parse_runbook(self, content: str) -> str:
        """Parse runbook format."""
        # Runbooks are typically markdown with specific structure
        return self._parse_markdown(content)

    # ==================== Chunking ====================

    def _chunk_content(
        self,
        content: str,
        content_type: ContentType,
    ) -> List[Tuple[str, Optional[str]]]:
        """
        Chunk content into pieces.

        Returns list of (text, section_header) tuples.
        """
        chunks = []

        if content_type == ContentType.MARKDOWN:
            chunks = self._chunk_markdown(content)
        elif content_type == ContentType.CODE:
            chunks = self._chunk_code(content)
        else:
            chunks = self._chunk_plain_text(content)

        return chunks

    def _chunk_markdown(self, content: str) -> List[Tuple[str, Optional[str]]]:
        """Chunk markdown by sections."""
        import re

        chunks = []
        current_section = None
        current_text = []

        lines = content.split("\n")

        for line in lines:
            # Check for headers
            header_match = re.match(r"^(#{1,6})\s+(.+)$", line)

            if header_match:
                # Save previous section
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        chunks.extend(self._split_if_needed(text, current_section))
                    current_text = []

                current_section = header_match.group(2)
                current_text.append(line)
            else:
                current_text.append(line)

        # Save final section
        if current_text:
            text = "\n".join(current_text).strip()
            if text:
                chunks.extend(self._split_if_needed(text, current_section))

        return chunks

    def _chunk_code(self, content: str) -> List[Tuple[str, Optional[str]]]:
        """Chunk code by logical units (functions, classes)."""
        chunks = []
        # Simple approach: chunk by empty lines with context
        paragraphs = content.split("\n\n")

        current_chunk = []
        current_size = 0

        for para in paragraphs:
            para_size = len(para.split())

            if current_size + para_size > self.config.chunking.target_chunk_size:
                if current_chunk:
                    chunks.append(("\n\n".join(current_chunk), None))
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size

        if current_chunk:
            chunks.append(("\n\n".join(current_chunk), None))

        return chunks

    def _chunk_plain_text(self, content: str) -> List[Tuple[str, Optional[str]]]:
        """Chunk plain text by paragraphs."""
        chunks = []
        paragraphs = content.split("\n\n")

        current_chunk = []
        current_size = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_size = len(para.split())

            if current_size + para_size > self.config.chunking.target_chunk_size:
                if current_chunk:
                    chunks.append(("\n\n".join(current_chunk), None))
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size

        if current_chunk:
            chunks.append(("\n\n".join(current_chunk), None))

        return chunks

    def _split_if_needed(
        self,
        text: str,
        section: Optional[str],
    ) -> List[Tuple[str, Optional[str]]]:
        """Split text if it exceeds max chunk size."""
        word_count = len(text.split())

        if word_count <= self.config.chunking.max_chunk_size:
            return [(text, section)]

        # Split into smaller chunks
        chunks = []
        words = text.split()
        target = self.config.chunking.target_chunk_size
        overlap = self.config.chunking.overlap_size

        i = 0
        while i < len(words):
            end = min(i + target, len(words))
            chunk_words = words[i:end]
            chunk_text = " ".join(chunk_words)
            chunks.append((chunk_text, section))
            i = end - overlap if end < len(words) else end

        return chunks

    # ==================== Extraction ====================

    def _extract_entities(self, text: str) -> List[str]:
        """Extract entities from text."""
        entities = []
        text_lower = text.lower()

        # Service patterns
        import re

        for match in re.finditer(r"\b([a-z]+-(?:service|api|db|cache))\b", text_lower):
            entities.append(f"service:{match.group(1)}")

        # Team patterns
        for match in re.finditer(r"\b(team [a-z]+|[a-z]+ team)\b", text_lower):
            entities.append(f"team:{match.group(1)}")

        # Technology patterns
        tech_keywords = [
            "kubernetes",
            "docker",
            "aws",
            "gcp",
            "postgres",
            "redis",
            "kafka",
        ]
        for tech in tech_keywords:
            if tech in text_lower:
                entities.append(f"technology:{tech}")

        return list(set(entities))

    def _extract_relationships(
        self,
        text: str,
        entities: List[str],
    ) -> List[Tuple[str, str, str]]:
        """Extract relationships from text."""
        relationships = []
        text_lower = text.lower()

        # Dependency patterns
        import re

        # "X depends on Y"
        for match in re.finditer(r"(\S+)\s+depends\s+on\s+(\S+)", text_lower):
            relationships.append((match.group(1), "depends_on", match.group(2)))

        # "X calls Y"
        for match in re.finditer(r"(\S+)\s+calls\s+(\S+)", text_lower):
            relationships.append((match.group(1), "calls", match.group(2)))

        # "X owned by Y"
        for match in re.finditer(
            r"(\S+)\s+(?:owned|maintained)\s+by\s+(\S+)", text_lower
        ):
            relationships.append((match.group(2), "owns", match.group(1)))

        return relationships

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        # Simple TF-based extraction
        import re

        words = re.findall(r"\b[a-z]{3,}\b", text.lower())

        # Remove common stop words
        stop_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "has",
            "had",
            "was",
            "were",
            "will",
            "with",
            "this",
            "that",
            "from",
            "they",
            "been",
            "have",
            "which",
            "their",
        }
        words = [w for w in words if w not in stop_words]

        # Count frequency
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1

        # Return top keywords
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:10]]

    def _infer_metadata(
        self,
        text: str,
        content_type: ContentType,
    ) -> Dict[str, Any]:
        """Infer metadata from content."""
        metadata = {}
        text_lower = text.lower()

        # Infer domain
        domains = {
            "incident": ["incident", "outage", "alert", "pagerduty"],
            "runbook": ["runbook", "procedure", "step 1", "how to"],
            "architecture": ["architecture", "design", "diagram", "component"],
            "onboarding": ["onboarding", "getting started", "setup", "install"],
        }

        for domain, keywords in domains.items():
            if any(kw in text_lower for kw in keywords):
                metadata["domain"] = domain
                break

        # Infer urgency
        if any(
            kw in text_lower for kw in ["critical", "urgent", "immediately", "asap"]
        ):
            metadata["urgency"] = "high"
        elif any(kw in text_lower for kw in ["important", "priority"]):
            metadata["urgency"] = "medium"

        return metadata

    def _compute_quality(self, text: str) -> float:
        """Compute quality score for a chunk."""
        score = 1.0

        # Penalize very short chunks
        word_count = len(text.split())
        if word_count < 20:
            score -= 0.3

        # Penalize chunks that are mostly special characters
        alpha_ratio = sum(c.isalpha() for c in text) / len(text) if text else 0
        if alpha_ratio < 0.5:
            score -= 0.2

        # Penalize repetitive content
        words = text.lower().split()
        if words:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < 0.3:
                score -= 0.3

        return max(0, score)

    # ==================== Stats ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return {
            "total_documents_processed": self._total_processed,
            "total_chunks_created": self._total_chunks,
            "unique_content_hashes": len(self._seen_hashes),
        }

    def reset_dedup_cache(self) -> None:
        """Clear the deduplication cache."""
        self._seen_hashes.clear()
