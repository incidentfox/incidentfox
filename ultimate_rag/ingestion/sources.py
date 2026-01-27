"""
Content Sources for Ultimate RAG.

Defines how to fetch content from various sources:
- Local files
- Git repositories
- Confluence/Wiki
- Slack
- APIs
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from .processor import ContentType

logger = logging.getLogger(__name__)


@dataclass
class SourceDocument:
    """A document from a content source."""

    source_id: str  # Unique identifier
    content: str
    content_type: ContentType

    # Source info
    source_name: str
    path: str  # Path/URL within source

    # Metadata
    title: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    version: Optional[str] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # For incremental sync
    content_hash: str = ""
    etag: Optional[str] = None

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.md5(self.content.encode()).hexdigest()


class ContentSource(ABC):
    """
    Base class for content sources.

    Implement this to add new sources (e.g., Notion, Google Docs).
    """

    name: str = "base"

    @abstractmethod
    def fetch_all(self) -> Iterator[SourceDocument]:
        """
        Fetch all documents from the source.

        Yields SourceDocument objects.
        """
        pass

    @abstractmethod
    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """
        Fetch documents updated since a given time.

        For incremental sync.
        """
        pass

    def fetch_one(self, document_id: str) -> Optional[SourceDocument]:
        """Fetch a specific document by ID."""
        return None


class FileSource(ContentSource):
    """
    Source for local file system.

    Supports:
    - Single files
    - Directories (recursive)
    - Glob patterns
    """

    name = "file"

    def __init__(
        self,
        path: Union[str, Path],
        patterns: Optional[List[str]] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
    ):
        self.path = Path(path)
        self.patterns = patterns or ["**/*.md", "**/*.txt", "**/*.html"]
        self.recursive = recursive
        self.exclude_patterns = exclude_patterns or [
            "**/node_modules/**",
            "**/.git/**",
            "**/venv/**",
            "**/__pycache__/**",
        ]

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch all files matching patterns."""
        if self.path.is_file():
            yield self._file_to_document(self.path)
            return

        for pattern in self.patterns:
            for file_path in self.path.glob(pattern):
                if not file_path.is_file():
                    continue

                # Check exclusions
                if self._should_exclude(file_path):
                    continue

                try:
                    yield self._file_to_document(file_path)
                except Exception as e:
                    logger.error(f"Failed to read {file_path}: {e}")

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """Fetch files modified since the given time."""
        for doc in self.fetch_all():
            if doc.updated_at and doc.updated_at > since:
                yield doc

    def _file_to_document(self, file_path: Path) -> SourceDocument:
        """Convert a file to SourceDocument."""
        content = file_path.read_text(encoding="utf-8")
        stat = file_path.stat()

        # Detect content type
        content_type = self._detect_type(file_path)

        return SourceDocument(
            source_id=str(file_path.absolute()),
            content=content,
            content_type=content_type,
            source_name=self.name,
            path=str(
                file_path.relative_to(self.path)
                if self.path.is_dir()
                else file_path.name
            ),
            title=file_path.stem,
            created_at=datetime.fromtimestamp(stat.st_ctime),
            updated_at=datetime.fromtimestamp(stat.st_mtime),
            metadata={
                "file_size": stat.st_size,
                "extension": file_path.suffix,
            },
        )

    def _detect_type(self, file_path: Path) -> ContentType:
        """Detect content type from file."""
        suffix = file_path.suffix.lower()
        mapping = {
            ".md": ContentType.MARKDOWN,
            ".markdown": ContentType.MARKDOWN,
            ".html": ContentType.HTML,
            ".htm": ContentType.HTML,
            ".txt": ContentType.TEXT,
            ".py": ContentType.CODE,
            ".js": ContentType.CODE,
            ".ts": ContentType.CODE,
        }
        return mapping.get(suffix, ContentType.TEXT)

    def _should_exclude(self, file_path: Path) -> bool:
        """Check if file should be excluded."""
        path_str = str(file_path)
        for pattern in self.exclude_patterns:
            import fnmatch

            if fnmatch.fnmatch(path_str, pattern):
                return True
        return False


class GitRepoSource(ContentSource):
    """
    Source for Git repositories.

    Features:
    - Clone/pull repositories
    - Track file history
    - Support multiple branches
    """

    name = "git"

    def __init__(
        self,
        repo_url: Optional[str] = None,
        local_path: Optional[Union[str, Path]] = None,
        branch: str = "main",
        patterns: Optional[List[str]] = None,
    ):
        self.repo_url = repo_url
        self.local_path = Path(local_path) if local_path else None
        self.branch = branch
        self.patterns = patterns or ["**/*.md", "docs/**/*"]

        # Will be set after clone/init
        self._file_source: Optional[FileSource] = None

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch all documents from the repository."""
        self._ensure_repo()

        if self._file_source:
            for doc in self._file_source.fetch_all():
                # Add git-specific metadata
                doc.metadata["git_repo"] = self.repo_url
                doc.metadata["git_branch"] = self.branch
                yield doc

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """Fetch documents updated since the given time."""
        self._ensure_repo()

        # Pull latest changes
        self._pull()

        if self._file_source:
            for doc in self._file_source.fetch_updated(since):
                doc.metadata["git_repo"] = self.repo_url
                doc.metadata["git_branch"] = self.branch
                yield doc

    def _ensure_repo(self) -> None:
        """Ensure repository is cloned/available."""
        if self._file_source:
            return

        if self.local_path and self.local_path.exists():
            self._file_source = FileSource(self.local_path, self.patterns)
        elif self.repo_url:
            # Would clone repo here
            logger.warning("Git clone not implemented - use local_path")

    def _pull(self) -> None:
        """Pull latest changes from remote."""
        if not self.local_path:
            return

        try:
            import subprocess

            subprocess.run(
                ["git", "pull", "origin", self.branch],
                cwd=self.local_path,
                capture_output=True,
            )
        except Exception as e:
            logger.error(f"Git pull failed: {e}")


class ConfluenceSource(ContentSource):
    """
    Source for Confluence/Wiki pages.

    Requires confluence-python library or REST API access.
    """

    name = "confluence"

    def __init__(
        self,
        base_url: str,
        space_key: str,
        username: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self.base_url = base_url
        self.space_key = space_key
        self.username = username
        self.api_token = api_token

        # Would initialize Confluence client here
        self._client = None

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch all pages from the space."""
        if not self._client:
            logger.warning("Confluence client not configured")
            return

        # Would fetch pages via API
        # pages = self._client.get_all_pages_from_space(self.space_key)
        # for page in pages:
        #     yield self._page_to_document(page)

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """Fetch pages updated since the given time."""
        if not self._client:
            return

        # Would use Confluence's CQL to query updated pages
        # cql = f"space = {self.space_key} and lastModified > '{since.isoformat()}'"

    def _page_to_document(self, page: Dict[str, Any]) -> SourceDocument:
        """Convert Confluence page to SourceDocument."""
        return SourceDocument(
            source_id=page.get("id", ""),
            content=page.get("body", {}).get("storage", {}).get("value", ""),
            content_type=ContentType.HTML,
            source_name=self.name,
            path=page.get("_links", {}).get("webui", ""),
            title=page.get("title"),
            author=page.get("version", {}).get("by", {}).get("displayName"),
            updated_at=datetime.fromisoformat(page.get("version", {}).get("when", "")),
            metadata={
                "space_key": self.space_key,
                "page_id": page.get("id"),
                "version": page.get("version", {}).get("number"),
            },
        )


class SlackSource(ContentSource):
    """
    Source for Slack conversations.

    Useful for capturing:
    - Incident discussions
    - Technical decisions
    - Team knowledge
    """

    name = "slack"

    def __init__(
        self,
        token: str,
        channels: List[str],
        include_threads: bool = True,
    ):
        self.token = token
        self.channels = channels
        self.include_threads = include_threads

        # Would initialize Slack client
        self._client = None

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch messages from configured channels."""
        if not self._client:
            logger.warning("Slack client not configured")
            return

        # Would fetch via Slack API
        # for channel in self.channels:
        #     messages = self._client.conversations_history(channel=channel)
        #     yield self._messages_to_document(channel, messages)

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """Fetch messages since the given time."""
        if not self._client:
            return

        # Would use oldest parameter in API call

    def _messages_to_document(
        self,
        channel: str,
        messages: List[Dict[str, Any]],
    ) -> SourceDocument:
        """Convert Slack messages to a document."""
        # Combine messages into a coherent document
        text_parts = []
        for msg in messages:
            user = msg.get("user", "unknown")
            text = msg.get("text", "")
            text_parts.append(f"[{user}]: {text}")

        return SourceDocument(
            source_id=f"slack_{channel}_{messages[0].get('ts', '')}",
            content="\n".join(text_parts),
            content_type=ContentType.SLACK_THREAD,
            source_name=self.name,
            path=f"#{channel}",
            title=f"Slack thread in #{channel}",
            metadata={
                "channel": channel,
                "message_count": len(messages),
            },
        )


class APIDocSource(ContentSource):
    """
    Source for API documentation (OpenAPI/Swagger).
    """

    name = "api_doc"

    def __init__(
        self,
        spec_url: Optional[str] = None,
        spec_path: Optional[Union[str, Path]] = None,
    ):
        self.spec_url = spec_url
        self.spec_path = Path(spec_path) if spec_path else None

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch and parse API documentation."""
        spec = self._load_spec()
        if not spec:
            return

        # Convert each endpoint to a document
        paths = spec.get("paths", {})
        for path, methods in paths.items():
            for method, details in methods.items():
                if isinstance(details, dict):
                    yield self._endpoint_to_document(path, method, details, spec)

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """API docs typically don't support incremental - fetch all."""
        return self.fetch_all()

    def _load_spec(self) -> Optional[Dict[str, Any]]:
        """Load OpenAPI spec."""
        import json

        try:
            if self.spec_path:
                content = self.spec_path.read_text()
            elif self.spec_url:
                import urllib.request

                with urllib.request.urlopen(self.spec_url) as response:
                    content = response.read().decode()
            else:
                return None

            # Try JSON first, then YAML
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                try:
                    import yaml

                    return yaml.safe_load(content)
                except Exception:
                    return None
        except Exception as e:
            logger.error(f"Failed to load API spec: {e}")
            return None

    def _endpoint_to_document(
        self,
        path: str,
        method: str,
        details: Dict[str, Any],
        spec: Dict[str, Any],
    ) -> SourceDocument:
        """Convert an API endpoint to a document."""
        # Build documentation text
        text_parts = [
            f"# {method.upper()} {path}",
            "",
            details.get("summary", ""),
            "",
            details.get("description", ""),
        ]

        # Add parameters
        params = details.get("parameters", [])
        if params:
            text_parts.append("\n## Parameters\n")
            for param in params:
                text_parts.append(
                    f"- **{param.get('name')}** ({param.get('in')}): "
                    f"{param.get('description', '')}"
                )

        # Add responses
        responses = details.get("responses", {})
        if responses:
            text_parts.append("\n## Responses\n")
            for code, resp in responses.items():
                text_parts.append(f"- **{code}**: {resp.get('description', '')}")

        return SourceDocument(
            source_id=f"api_{method}_{path}",
            content="\n".join(text_parts),
            content_type=ContentType.API_DOC,
            source_name=self.name,
            path=path,
            title=f"{method.upper()} {path}",
            metadata={
                "method": method,
                "path": path,
                "tags": details.get("tags", []),
                "api_title": spec.get("info", {}).get("title"),
            },
        )
