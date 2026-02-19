"""
GitHub Integration Scanner.

Scans a GitHub organization for:
1. Operational docs (README, runbooks, incident response)
2. Architecture signal files (Dockerfile, k8s manifests, CI configs, dependency files)
3. LLM-generated service map summarizing the codebase architecture

Calls the GitHub API directly using credentials fetched from config_service.
"""

import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import Document, register_scanner


def _log(event: str, **fields) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "scanners.github",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


# --- File path configs ---

# Operational docs to ingest directly into RAG
OPS_DOC_PATHS = [
    "README.md",
    "docs/runbook.md",
    "docs/runbooks/",
    "runbook.md",
    "RUNBOOK.md",
    "docs/oncall.md",
    "docs/on-call.md",
    "docs/incident-response.md",
    "docs/architecture.md",
    "docs/ops.md",
    ".github/INCIDENT_RESPONSE.md",
]

# Files that reveal architecture (read for LLM analysis, not ingested raw)
INFRA_SIGNAL_FILES = [
    # Container & orchestration
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    # Kubernetes
    "k8s/deployment.yaml",
    "k8s/service.yaml",
    "kubernetes/deployment.yaml",
    "deploy/deployment.yaml",
    "charts/values.yaml",
    "helm/values.yaml",
    # CI/CD
    ".github/workflows/",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    # Dependencies (reveal tech stack)
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    # App config (reveals external dependencies)
    ".env.example",
    ".env.sample",
]

MAX_REPOS = 20
MAX_FILE_SIZE = 100_000  # 100KB
MAX_SIGNAL_FILE_SIZE = 50_000  # 50KB — signal files should be small


# --- LLM prompt for architecture summarization ---

ARCHITECTURE_PROMPT = """You are an SRE expert analyzing a software organization's GitHub repositories.

Given the infrastructure and configuration files below from the "{org}" GitHub organization, produce a structured architecture summary that an AI SRE agent can use during incidents.

## Repository Data

{repo_summaries}

## Instructions

Analyze the files and produce a JSON response with this structure:
{{
  "services": [
    {{
      "name": "service-name",
      "repo": "org/repo-name",
      "language": "Python",
      "framework": "FastAPI",
      "dependencies": ["PostgreSQL", "Redis", "other-service"],
      "deployment": "Kubernetes",
      "description": "One sentence describing what this service does"
    }}
  ],
  "infrastructure": {{
    "orchestration": "Kubernetes",
    "ci_cd": "GitHub Actions",
    "cloud_provider": "AWS",
    "databases": ["PostgreSQL", "Redis"],
    "message_queues": [],
    "monitoring": ["Prometheus", "Grafana"]
  }},
  "service_dependencies": [
    {{"from": "api-gateway", "to": "user-service", "type": "HTTP"}},
    {{"from": "worker", "to": "Redis", "type": "queue"}}
  ],
  "key_observations": [
    "Short bullet points about important architectural patterns"
  ]
}}

Rules:
- Only include information you can clearly infer from the files. Don't guess.
- For dependencies, look at imports, env vars, connection strings, docker-compose links.
- If a repo has no signal files, skip it.
- Keep descriptions concise — this will be used as context during incidents."""


# --- GitHub API helpers ---


def _github_api(
    path: str,
    token: str,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """Make a GitHub API request."""
    url = f"https://api.github.com{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "IncidentFox-Scanner")

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # Expected for missing files
        _log("github_api_error", path=path, status=e.code)
        return None
    except Exception as e:
        _log("github_api_failed", path=path, error=str(e))
        return None


def _list_repos(token: str, org: str) -> List[Dict[str, Any]]:
    """List repos for an org (or user if not an org)."""
    repos = _github_api(
        f"/orgs/{org}/repos", token, {"per_page": 100, "sort": "pushed"}
    )
    if repos is not None:
        return repos[:MAX_REPOS]

    repos = _github_api(
        f"/users/{org}/repos", token, {"per_page": 100, "sort": "pushed"}
    )
    return (repos or [])[:MAX_REPOS]


def _get_file_content(
    token: str, owner: str, repo: str, path: str, max_size: int = MAX_FILE_SIZE
) -> Optional[str]:
    """Fetch a file's decoded content from a repo."""
    data = _github_api(f"/repos/{owner}/{repo}/contents/{path}", token)
    if not data:
        return None

    # Handle directory listing — fetch first few YAML/JSON files
    if isinstance(data, list):
        return _get_directory_sample(token, owner, repo, path, data, max_size)

    if data.get("size", 0) > max_size:
        return None

    content_b64 = data.get("content", "")
    if not content_b64:
        return None

    try:
        return base64.b64decode(content_b64).decode("utf-8")
    except Exception:
        return None


def _get_directory_sample(
    token: str,
    owner: str,
    repo: str,
    dir_path: str,
    listing: List[Dict[str, Any]],
    max_size: int,
) -> Optional[str]:
    """For directory paths, fetch a sample of relevant files."""
    relevant_extensions = {".yaml", ".yml", ".json", ".toml", ".md"}
    parts = []

    for item in listing[:5]:  # Cap at 5 files per directory
        name = item.get("name", "")
        if item.get("type") != "file":
            continue
        if not any(name.endswith(ext) for ext in relevant_extensions):
            continue

        content = _get_file_content(token, owner, repo, f"{dir_path}/{name}", max_size)
        if content:
            parts.append(f"--- {dir_path}/{name} ---\n{content}")

    return "\n\n".join(parts) if parts else None


# --- Core scanning logic ---


def _scan_ops_docs(
    token: str, repos: List[Dict[str, Any]], github_org: str, org_id: str
) -> List[Document]:
    """Scan repos for operational documents (README, runbooks, etc.)."""
    documents: List[Document] = []

    for repo_data in repos:
        repo_name = repo_data.get("name", "")
        full_name = repo_data.get("full_name", f"{github_org}/{repo_name}")
        owner = full_name.split("/")[0] if "/" in full_name else github_org

        for doc_path in OPS_DOC_PATHS:
            content = _get_file_content(token, owner, repo_name, doc_path)
            if content and len(content) >= 50:
                documents.append(
                    Document(
                        content=content,
                        source_url=f"https://github.com/{full_name}/blob/main/{doc_path}",
                        content_type="markdown",
                        metadata={
                            "repo": full_name,
                            "path": doc_path,
                            "org_id": org_id,
                            "source": "integration_scan",
                        },
                    )
                )

    return documents


def _collect_infra_signals(
    token: str, repos: List[Dict[str, Any]], github_org: str
) -> Dict[str, Dict[str, str]]:
    """Collect infrastructure signal files from repos.

    Returns: {repo_full_name: {file_path: file_content}}
    """
    repo_signals: Dict[str, Dict[str, str]] = {}

    for repo_data in repos:
        repo_name = repo_data.get("name", "")
        full_name = repo_data.get("full_name", f"{github_org}/{repo_name}")
        owner = full_name.split("/")[0] if "/" in full_name else github_org
        files_found: Dict[str, str] = {}

        for signal_path in INFRA_SIGNAL_FILES:
            content = _get_file_content(
                token, owner, repo_name, signal_path, MAX_SIGNAL_FILE_SIZE
            )
            if content and len(content) >= 10:
                # Truncate large files to keep LLM context manageable
                files_found[signal_path] = content[:10_000]

        if files_found:
            repo_signals[full_name] = files_found

    return repo_signals


def _format_repo_summaries(repo_signals: Dict[str, Dict[str, str]]) -> str:
    """Format collected signal files into a text block for the LLM prompt."""
    parts = []
    for repo_name, files in repo_signals.items():
        repo_section = [f"### Repository: {repo_name}"]
        for file_path, content in files.items():
            repo_section.append(f"\n**{file_path}**:\n```\n{content}\n```")
        parts.append("\n".join(repo_section))

    return "\n\n---\n\n".join(parts)


async def _generate_architecture_summary(
    repo_signals: Dict[str, Dict[str, str]],
    github_org: str,
    org_id: str,
) -> Optional[Document]:
    """Use LLM to generate an architecture summary from infra signal files."""
    if not repo_signals:
        return None

    repo_summaries = _format_repo_summaries(repo_signals)

    # Don't send more than ~80K chars to the LLM
    if len(repo_summaries) > 80_000:
        repo_summaries = repo_summaries[:80_000] + "\n\n[... truncated ...]"

    prompt = ARCHITECTURE_PROMPT.format(
        org=github_org,
        repo_summaries=repo_summaries,
    )

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        response = await client.chat.completions.create(
            model=os.getenv("SCANNER_LLM_MODEL", "gpt-4o-mini"),
            temperature=0.1,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        architecture = json.loads(raw)

        # Format as a human-readable + machine-parseable document
        summary_text = _format_architecture_document(architecture, github_org)

        _log(
            "architecture_summary_generated",
            org=github_org,
            services=len(architecture.get("services", [])),
            repos_analyzed=len(repo_signals),
        )

        return Document(
            content=summary_text,
            source_url=f"github://{github_org}/architecture-map",
            content_type="text",
            metadata={
                "org_id": org_id,
                "source": "integration_scan",
                "document_type": "architecture_map",
                "repos_analyzed": list(repo_signals.keys()),
                "raw_architecture": architecture,
            },
        )

    except Exception as e:
        _log("architecture_summary_failed", error=str(e))
        return None


def _format_architecture_document(architecture: Dict[str, Any], org: str) -> str:
    """Format the LLM's JSON output into a readable document for RAG."""
    lines = [f"# Architecture Map: {org}", ""]

    # Services
    services = architecture.get("services", [])
    if services:
        lines.append("## Services")
        lines.append("")
        for svc in services:
            name = svc.get("name", "unknown")
            lang = svc.get("language", "")
            framework = svc.get("framework", "")
            repo = svc.get("repo", "")
            desc = svc.get("description", "")
            deps = svc.get("dependencies", [])
            deploy = svc.get("deployment", "")

            tech = f"{lang}/{framework}" if framework else lang
            lines.append(f"### {name}")
            if desc:
                lines.append(f"{desc}")
            lines.append(f"- **Repo**: {repo}")
            if tech:
                lines.append(f"- **Tech**: {tech}")
            if deploy:
                lines.append(f"- **Deployment**: {deploy}")
            if deps:
                lines.append(f"- **Dependencies**: {', '.join(deps)}")
            lines.append("")

    # Infrastructure
    infra = architecture.get("infrastructure", {})
    if infra:
        lines.append("## Infrastructure")
        lines.append("")
        for key, value in infra.items():
            label = key.replace("_", " ").title()
            if isinstance(value, list):
                if value:
                    lines.append(f"- **{label}**: {', '.join(value)}")
            elif value:
                lines.append(f"- **{label}**: {value}")
        lines.append("")

    # Service dependencies
    deps = architecture.get("service_dependencies", [])
    if deps:
        lines.append("## Service Dependencies")
        lines.append("")
        for dep in deps:
            lines.append(
                f"- {dep.get('from', '?')} → {dep.get('to', '?')} ({dep.get('type', 'unknown')})"
            )
        lines.append("")

    # Key observations
    observations = architecture.get("key_observations", [])
    if observations:
        lines.append("## Key Observations")
        lines.append("")
        for obs in observations:
            lines.append(f"- {obs}")
        lines.append("")

    return "\n".join(lines)


# --- Main scanner entry point ---


@register_scanner("github")
async def scan(
    credentials: Dict[str, Any],
    config: Dict[str, Any],
    org_id: str,
) -> List[Document]:
    """
    Scan GitHub for operational documents and architecture context.

    Two passes:
    1. Fetch operational docs (README, runbooks) — ingested as-is
    2. Fetch infra signal files → LLM generates architecture map — ingested as summary
    """
    token = credentials.get("api_key") or credentials.get("token", "")
    if not token:
        _log("no_github_token")
        return []

    github_org = (
        config.get("account_login")
        or config.get("default_org")
        or config.get("org", "")
    )
    if not github_org:
        _log("no_github_org")
        return []

    _log("github_scan_started", org=github_org)

    repos = _list_repos(token, github_org)
    if not repos:
        _log("no_repos_found", org=github_org)
        return []

    documents: List[Document] = []

    # Pass 1: Operational docs (direct ingestion)
    ops_docs = _scan_ops_docs(token, repos, github_org, org_id)
    documents.extend(ops_docs)

    # Pass 2: Architecture map (LLM-generated summary)
    repo_signals = _collect_infra_signals(token, repos, github_org)
    if repo_signals:
        arch_doc = await _generate_architecture_summary(
            repo_signals, github_org, org_id
        )
        if arch_doc:
            documents.append(arch_doc)

    _log(
        "github_scan_completed",
        repos_scanned=len(repos),
        ops_docs=len(ops_docs),
        repos_with_infra_signals=len(repo_signals),
        total_documents=len(documents),
    )
    return documents
