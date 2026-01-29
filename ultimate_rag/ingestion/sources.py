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
    - SSH and HTTPS support
    """

    name = "git"

    def __init__(
        self,
        repo_url: Optional[str] = None,
        local_path: Optional[Union[str, Path]] = None,
        branch: str = "main",
        patterns: Optional[List[str]] = None,
        clone_dir: Optional[Union[str, Path]] = None,
        depth: Optional[int] = None,
    ):
        self.repo_url = repo_url
        self.local_path = Path(local_path) if local_path else None
        self.branch = branch
        self.patterns = patterns or ["**/*.md", "docs/**/*"]
        self.clone_dir = (
            Path(clone_dir) if clone_dir else Path("/tmp/ultimate_rag_repos")
        )
        self.depth = depth  # Shallow clone depth, None for full clone

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

                # Try to get git blame info for the file
                commit_info = self._get_file_commit_info(doc.path)
                if commit_info:
                    doc.metadata.update(commit_info)

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
            cloned_path = self._clone_repo()
            if cloned_path:
                self.local_path = cloned_path
                self._file_source = FileSource(cloned_path, self.patterns)
        else:
            logger.warning("No repo_url or local_path specified")

    def _clone_repo(self) -> Optional[Path]:
        """Clone the repository."""
        import hashlib
        import subprocess

        if not self.repo_url:
            return None

        # Create a unique directory name from the repo URL
        repo_hash = hashlib.md5(self.repo_url.encode()).hexdigest()[:12]
        repo_name = self.repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        clone_path = self.clone_dir / f"{repo_name}_{repo_hash}"

        # Create clone directory if it doesn't exist
        self.clone_dir.mkdir(parents=True, exist_ok=True)

        if clone_path.exists():
            # Repo already cloned, just pull
            logger.info(f"Repository already cloned at {clone_path}, pulling latest...")
            try:
                subprocess.run(
                    ["git", "fetch", "origin"],
                    cwd=clone_path,
                    capture_output=True,
                    check=True,
                    timeout=120,
                )
                subprocess.run(
                    ["git", "checkout", self.branch],
                    cwd=clone_path,
                    capture_output=True,
                    timeout=30,
                )
                subprocess.run(
                    ["git", "reset", "--hard", f"origin/{self.branch}"],
                    cwd=clone_path,
                    capture_output=True,
                    timeout=30,
                )
                return clone_path
            except Exception as e:
                logger.error(f"Failed to update existing repo: {e}")
                # Try to remove and re-clone
                import shutil

                shutil.rmtree(clone_path, ignore_errors=True)

        # Clone the repository
        logger.info(f"Cloning repository {self.repo_url} to {clone_path}...")
        try:
            cmd = ["git", "clone"]

            # Add shallow clone flag if depth specified
            if self.depth:
                cmd.extend(["--depth", str(self.depth)])

            # Add branch
            cmd.extend(["--branch", self.branch])

            # Add single-branch to speed up clone
            cmd.append("--single-branch")

            cmd.extend([self.repo_url, str(clone_path)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for large repos
            )

            if result.returncode != 0:
                logger.error(f"Git clone failed: {result.stderr}")
                return None

            logger.info(f"Successfully cloned repository to {clone_path}")
            return clone_path

        except subprocess.TimeoutExpired:
            logger.error(f"Git clone timed out for {self.repo_url}")
            return None
        except Exception as e:
            logger.error(f"Git clone failed: {e}")
            return None

    def _pull(self) -> None:
        """Pull latest changes from remote."""
        if not self.local_path:
            return

        try:
            import subprocess

            # Fetch first
            subprocess.run(
                ["git", "fetch", "origin", self.branch],
                cwd=self.local_path,
                capture_output=True,
                timeout=120,
            )

            # Then reset to remote branch
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{self.branch}"],
                cwd=self.local_path,
                capture_output=True,
                timeout=30,
            )

            logger.info(f"Pulled latest changes for {self.repo_url}")
        except Exception as e:
            logger.error(f"Git pull failed: {e}")

    def _get_file_commit_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get the last commit info for a file."""
        if not self.local_path:
            return None

        try:
            import subprocess

            full_path = self.local_path / file_path
            if not full_path.exists():
                return None

            # Get last commit info
            result = subprocess.run(
                ["git", "log", "-1", "--format=%H|%an|%ae|%aI|%s", "--", file_path],
                cwd=self.local_path,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split("|", 4)
                if len(parts) >= 5:
                    return {
                        "git_commit_hash": parts[0],
                        "git_author_name": parts[1],
                        "git_author_email": parts[2],
                        "git_commit_date": parts[3],
                        "git_commit_message": parts[4],
                    }
        except Exception as e:
            logger.debug(f"Failed to get git info for {file_path}: {e}")

        return None


class ConfluenceSource(ContentSource):
    """
    Source for Confluence/Wiki pages.

    Uses Confluence REST API for fetching pages.
    """

    name = "confluence"

    def __init__(
        self,
        base_url: str,
        space_key: str,
        username: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.space_key = space_key
        self.username = username
        self.api_token = api_token
        self._session = None

    def _get_session(self):
        """Get or create HTTP session with auth."""
        if self._session is None:
            import requests

            self._session = requests.Session()
            if self.username and self.api_token:
                self._session.auth = (self.username, self.api_token)
            self._session.headers.update(
                {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
            )
        return self._session

    def _api_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make API request to Confluence."""
        try:
            session = self._get_session()
            url = f"{self.base_url}/rest/api{endpoint}"
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Confluence API request failed: {e}")
            return None

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch all pages from the space."""
        if not self.username or not self.api_token:
            logger.warning("Confluence credentials not configured")
            return

        start = 0
        limit = 50

        while True:
            params = {
                "spaceKey": self.space_key,
                "expand": "body.storage,version,ancestors",
                "start": start,
                "limit": limit,
            }

            result = self._api_request("/content", params)
            if not result:
                break

            pages = result.get("results", [])
            if not pages:
                break

            for page in pages:
                try:
                    yield self._page_to_document(page)
                except Exception as e:
                    logger.error(f"Failed to process page {page.get('id')}: {e}")

            # Check if there are more pages
            if len(pages) < limit:
                break
            start += limit

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """Fetch pages updated since the given time."""
        if not self.username or not self.api_token:
            logger.warning("Confluence credentials not configured")
            return

        # Use CQL (Confluence Query Language) to find updated pages
        since_str = since.strftime("%Y-%m-%d %H:%M")
        cql = f'space = "{self.space_key}" and lastModified >= "{since_str}"'

        start = 0
        limit = 50

        while True:
            params = {
                "cql": cql,
                "expand": "body.storage,version,ancestors",
                "start": start,
                "limit": limit,
            }

            result = self._api_request("/content/search", params)
            if not result:
                break

            pages = result.get("results", [])
            if not pages:
                break

            for page in pages:
                try:
                    yield self._page_to_document(page)
                except Exception as e:
                    logger.error(f"Failed to process page {page.get('id')}: {e}")

            if len(pages) < limit:
                break
            start += limit

    def fetch_one(self, document_id: str) -> Optional[SourceDocument]:
        """Fetch a specific page by ID."""
        params = {"expand": "body.storage,version,ancestors"}
        result = self._api_request(f"/content/{document_id}", params)
        if result:
            return self._page_to_document(result)
        return None

    def _page_to_document(self, page: Dict[str, Any]) -> SourceDocument:
        """Convert Confluence page to SourceDocument."""
        # Parse the update timestamp
        version_when = page.get("version", {}).get("when", "")
        updated_at = None
        if version_when:
            try:
                # Confluence uses ISO format with timezone
                updated_at = datetime.fromisoformat(version_when.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Build path from ancestors
        ancestors = page.get("ancestors", [])
        path_parts = [a.get("title", "") for a in ancestors]
        path_parts.append(page.get("title", ""))
        path = " / ".join(path_parts)

        return SourceDocument(
            source_id=f"confluence_{page.get('id', '')}",
            content=page.get("body", {}).get("storage", {}).get("value", ""),
            content_type=ContentType.HTML,
            source_name=self.name,
            path=path,
            title=page.get("title"),
            author=page.get("version", {}).get("by", {}).get("displayName"),
            updated_at=updated_at,
            metadata={
                "space_key": self.space_key,
                "page_id": page.get("id"),
                "version": page.get("version", {}).get("number"),
                "web_url": page.get("_links", {}).get("webui", ""),
            },
        )


class SlackSource(ContentSource):
    """
    Source for Slack conversations.

    Useful for capturing:
    - Incident discussions
    - Technical decisions
    - Team knowledge

    Uses Slack Web API for fetching messages.
    """

    name = "slack"

    def __init__(
        self,
        token: str,
        channels: List[str],
        include_threads: bool = True,
        group_by_thread: bool = True,
    ):
        self.token = token
        self.channels = channels
        self.include_threads = include_threads
        self.group_by_thread = group_by_thread
        self._user_cache: Dict[str, str] = {}

    def _api_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make API request to Slack."""
        import json
        import urllib.parse
        import urllib.request

        try:
            url = f"https://slack.com/api/{method}"
            if params:
                url = f"{url}?{urllib.parse.urlencode(params)}"

            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if not data.get("ok"):
                    logger.error(f"Slack API error: {data.get('error')}")
                    return None
                return data
        except Exception as e:
            logger.error(f"Slack API request failed: {e}")
            return None

    def _get_user_name(self, user_id: str) -> str:
        """Get user display name from cache or API."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        result = self._api_request("users.info", {"user": user_id})
        if result and result.get("user"):
            user = result["user"]
            name = user.get("real_name") or user.get("name") or user_id
            self._user_cache[user_id] = name
            return name

        self._user_cache[user_id] = user_id
        return user_id

    def _get_channel_id(self, channel_name: str) -> Optional[str]:
        """Get channel ID from name."""
        # Remove # prefix if present
        channel_name = channel_name.lstrip("#")

        result = self._api_request("conversations.list", {"limit": 1000})
        if result and result.get("channels"):
            for channel in result["channels"]:
                if channel.get("name") == channel_name:
                    return channel.get("id")
        return None

    def fetch_all(self) -> Iterator[SourceDocument]:
        """Fetch messages from configured channels."""
        if not self.token:
            logger.warning("Slack token not configured")
            return

        for channel in self.channels:
            channel_id = (
                self._get_channel_id(channel)
                if not channel.startswith("C")
                else channel
            )
            if not channel_id:
                logger.warning(f"Could not find channel: {channel}")
                continue

            for doc in self._fetch_channel_messages(channel_id, channel):
                yield doc

    def fetch_updated(
        self,
        since: datetime,
    ) -> Iterator[SourceDocument]:
        """Fetch messages since the given time."""
        if not self.token:
            logger.warning("Slack token not configured")
            return

        oldest = str(since.timestamp())

        for channel in self.channels:
            channel_id = (
                self._get_channel_id(channel)
                if not channel.startswith("C")
                else channel
            )
            if not channel_id:
                continue

            for doc in self._fetch_channel_messages(channel_id, channel, oldest=oldest):
                yield doc

    def _fetch_channel_messages(
        self,
        channel_id: str,
        channel_name: str,
        oldest: Optional[str] = None,
    ) -> Iterator[SourceDocument]:
        """Fetch messages from a specific channel."""
        cursor = None
        all_messages: List[Dict[str, Any]] = []
        threads: Dict[str, List[Dict[str, Any]]] = {}

        while True:
            params: Dict[str, Any] = {
                "channel": channel_id,
                "limit": 200,
            }
            if oldest:
                params["oldest"] = oldest
            if cursor:
                params["cursor"] = cursor

            result = self._api_request("conversations.history", params)
            if not result:
                break

            messages = result.get("messages", [])
            all_messages.extend(messages)

            # Fetch thread replies if enabled
            if self.include_threads:
                for msg in messages:
                    if msg.get("thread_ts") and msg.get("reply_count", 0) > 0:
                        thread_ts = msg["thread_ts"]
                        thread_result = self._api_request(
                            "conversations.replies",
                            {"channel": channel_id, "ts": thread_ts},
                        )
                        if thread_result:
                            threads[thread_ts] = thread_result.get("messages", [])

            # Check for more pages
            response_metadata = result.get("response_metadata", {})
            cursor = response_metadata.get("next_cursor")
            if not cursor:
                break

        # Group messages and convert to documents
        if self.group_by_thread:
            # Yield thread documents
            for thread_ts, thread_messages in threads.items():
                if len(thread_messages) > 1:
                    yield self._thread_to_document(channel_name, thread_messages)

            # Yield non-thread messages as individual or grouped documents
            non_thread_messages = [
                m
                for m in all_messages
                if not m.get("thread_ts") or m.get("ts") == m.get("thread_ts")
            ]
            if non_thread_messages:
                yield self._messages_to_document(channel_name, non_thread_messages)
        else:
            # Yield all messages as a single document
            if all_messages:
                yield self._messages_to_document(channel_name, all_messages)

    def _thread_to_document(
        self,
        channel: str,
        messages: List[Dict[str, Any]],
    ) -> SourceDocument:
        """Convert a Slack thread to a document."""
        # Sort by timestamp
        messages = sorted(messages, key=lambda m: float(m.get("ts", 0)))

        text_parts = []
        for msg in messages:
            user_id = msg.get("user", "unknown")
            user_name = (
                self._get_user_name(user_id) if user_id != "unknown" else "unknown"
            )
            text = msg.get("text", "")
            ts = float(msg.get("ts", 0))
            timestamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            text_parts.append(f"[{timestamp}] {user_name}: {text}")

        thread_ts = messages[0].get("thread_ts", messages[0].get("ts", ""))

        return SourceDocument(
            source_id=f"slack_thread_{channel}_{thread_ts}",
            content="\n".join(text_parts),
            content_type=ContentType.SLACK_THREAD,
            source_name=self.name,
            path=f"#{channel}/thread/{thread_ts}",
            title=f"Thread in #{channel}",
            created_at=datetime.fromtimestamp(float(thread_ts)) if thread_ts else None,
            metadata={
                "channel": channel,
                "thread_ts": thread_ts,
                "message_count": len(messages),
                "participants": list(
                    set(m.get("user", "") for m in messages if m.get("user"))
                ),
            },
        )

    def _messages_to_document(
        self,
        channel: str,
        messages: List[Dict[str, Any]],
    ) -> SourceDocument:
        """Convert Slack messages to a document."""
        # Sort by timestamp
        messages = sorted(messages, key=lambda m: float(m.get("ts", 0)))

        text_parts = []
        for msg in messages:
            user_id = msg.get("user", "unknown")
            user_name = (
                self._get_user_name(user_id) if user_id != "unknown" else "unknown"
            )
            text = msg.get("text", "")
            ts = float(msg.get("ts", 0))
            timestamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            text_parts.append(f"[{timestamp}] {user_name}: {text}")

        first_ts = messages[0].get("ts", "") if messages else ""
        last_ts = messages[-1].get("ts", "") if messages else ""

        return SourceDocument(
            source_id=f"slack_{channel}_{first_ts}_{last_ts}",
            content="\n".join(text_parts),
            content_type=ContentType.SLACK_THREAD,
            source_name=self.name,
            path=f"#{channel}",
            title=f"Messages in #{channel}",
            created_at=datetime.fromtimestamp(float(first_ts)) if first_ts else None,
            updated_at=datetime.fromtimestamp(float(last_ts)) if last_ts else None,
            metadata={
                "channel": channel,
                "message_count": len(messages),
                "participants": list(
                    set(m.get("user", "") for m in messages if m.get("user"))
                ),
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
