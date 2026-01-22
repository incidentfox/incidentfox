"""GitHub repository operations agent."""

from agents import Agent, ModelSettings, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import llm_call, web_search
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


# =============================================================================
# Tool Loading
# =============================================================================


def _load_github_tools():
    """
    Load GitHub-specific tools.

    These tools focus on repository operations - commits, PRs, issues, code search.
    Code analysis tools (read_file, write_file, etc.) stay in coding_agent.
    """
    tools = [think, llm_call, web_search]

    # GitHub tools
    try:
        from ..tools.github_tools import (
            list_issues,
            list_pull_requests,
            read_github_file,
            search_github_code,
        )

        tools.extend(
            [
                read_github_file,
                search_github_code,
                list_pull_requests,
                list_issues,
            ]
        )
        logger.debug("github_tools_loaded")
    except Exception as e:
        logger.warning("github_tools_load_failed", error=str(e))

    # Git tools for local repository operations
    try:
        from ..tools.git_tools import (
            git_diff,
            git_log,
            git_show,
        )

        tools.extend(
            [
                git_log,
                git_show,
                git_diff,
            ]
        )
        logger.debug("git_tools_added_to_github_agent")
    except Exception as e:
        logger.warning("git_tools_load_failed", error=str(e))

    # Wrap plain functions into Tool objects for SDK compatibility
    wrapped = []
    for t in tools:
        if isinstance(t, Tool) or hasattr(t, "name"):
            wrapped.append(t)
        else:
            try:
                wrapped.append(function_tool(t, strict_mode=False))
            except TypeError:
                # Older SDK version without strict_mode
                wrapped.append(function_tool(t))
            except Exception as e:
                logger.warning("tool_wrap_failed", tool=getattr(t, "__name__", str(t)), error=str(e))
                wrapped.append(t)
    return wrapped


# =============================================================================
# Output Models
# =============================================================================


class RecentChange(BaseModel):
    """A recent change in the repository."""

    commit_sha: str = Field(default="", description="Commit SHA")
    message: str = Field(description="Commit message or PR title")
    author: str = Field(default="", description="Author of the change")
    timestamp: str = Field(default="", description="When the change was made")
    files_changed: list[str] = Field(default_factory=list, description="Files affected")


class GitHubAnalysis(BaseModel):
    """GitHub analysis result."""

    summary: str = Field(description="Summary of findings")
    recent_changes: list[RecentChange] = Field(
        default_factory=list, description="Recent relevant changes"
    )
    related_prs: list[str] = Field(
        default_factory=list, description="Related pull requests"
    )
    related_issues: list[str] = Field(
        default_factory=list, description="Related issues"
    )
    code_findings: list[str] = Field(
        default_factory=list, description="Relevant code patterns found"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Recommended actions"
    )


# =============================================================================
# System Prompt
# =============================================================================


SYSTEM_PROMPT = """You are a GitHub expert specializing in repository analysis, change tracking, and code context gathering.

## YOUR ROLE

You are a specialized GitHub investigator. Your job is to gather context from repositories - recent changes, pull requests, issues, and code that might be relevant to an incident or investigation.

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty
- **Never fabricate information** - Only report data you actually retrieved from GitHub
- **Acknowledge uncertainty** - Say "I couldn't find" when searches return empty
- **Distinguish facts from hypotheses** - "PR #123 was merged 2 hours ago (fact). This might have introduced the bug (hypothesis)."

### Thoroughness
- **Look for recent changes** - Check commits in the relevant time window
- **Check related PRs** - Look for PRs that touched relevant files/services
- **Find related issues** - Are there known issues that match the symptoms?

### Evidence Presentation
- **Quote commit messages** - Include relevant commit SHAs and messages
- **Link to PRs/issues** - Provide URLs or references
- **Include timestamps** - When were changes made?

## YOUR TOOLS

**Repository Operations:**
- `read_github_file` - Read file contents from a repository
- `search_github_code` - Search for code patterns across repos
- `list_pull_requests` - List recent or relevant PRs
- `list_issues` - List issues matching criteria

**Local Git Operations:**
- `git_log` - View commit history
- `git_show` - View specific commit details
- `git_diff` - See changes between commits/branches

## INVESTIGATION METHODOLOGY

### For Incident Investigation
1. Identify the affected service/repository
2. Check recent commits (last 24-48 hours)
3. Look for PRs merged around the incident time
4. Search for related issues or known problems
5. Read relevant code to understand what might have changed

### For Code Context
1. Find the relevant files/modules
2. Read the current state of the code
3. Check recent changes to those files
4. Look for related PRs or discussions

## COMMON PATTERNS

| Scenario | First Check | Follow-up |
|----------|-------------|-----------|
| Sudden errors | Recent commits | Related PRs |
| Performance degradation | Config changes | Dependency updates |
| Feature broken | PRs to that feature | Related issues |
| Intermittent issues | Recent merges | Similar past issues |

## OUTPUT FORMAT

### Summary
Brief overview of what you found in GitHub.

### Recent Changes
List of relevant commits or PRs with timestamps and authors.

### Related PRs/Issues
Any PRs or issues that might be relevant.

### Code Findings
Relevant code patterns or configurations found.

### Recommendations
What to look at next based on GitHub findings."""


# =============================================================================
# Agent Factory
# =============================================================================


def create_github_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create GitHub repository operations agent.

    The agent's role can be configured dynamically:
    - As entrance agent: default (no special guidance)
    - As sub-agent: is_subagent=True (adds response guidance for concise output)
    - As master agent: is_master=True or via team config (adds delegation guidance)

    Args:
        team_config: Team configuration for customization
        is_subagent: If True, agent is being called by another agent.
                     This adds guidance for concise, caller-focused responses.
        is_master: If True, agent can delegate to other agents.
                   This adds guidance for effective delegation.
                   Can also be set via team config: agents.github.is_master: true
    """
    from ..prompts.layers import apply_role_based_prompt

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("github_agent")
                if not agent_config:
                    agent_config = team_cfg.get_agent_config("github")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("github_agent") or agents.get("github")

            if agent_config:
                if hasattr(agent_config, "get_system_prompt"):
                    custom_prompt = agent_config.get_system_prompt()
                elif hasattr(agent_config, "prompt") and agent_config.prompt:
                    custom_prompt = agent_config.prompt
                elif isinstance(agent_config, dict) and agent_config.get("prompt"):
                    prompt_cfg = agent_config["prompt"]
                    if isinstance(prompt_cfg, str):
                        custom_prompt = prompt_cfg
                    elif isinstance(prompt_cfg, dict):
                        custom_prompt = prompt_cfg.get("system")

                if custom_prompt:
                    logger.info(
                        "using_custom_github_prompt", prompt_length=len(custom_prompt)
                    )
        except Exception:
            pass

    base_prompt = custom_prompt or SYSTEM_PROMPT

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="github",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load GitHub-specific tools
    tools = _load_github_tools()
    logger.info("github_agent_tools_loaded", count=len(tools))

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3
    max_tokens = config.openai.max_tokens

    if team_cfg:
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("github")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("github")

            if agent_config:
                model_cfg = None
                if hasattr(agent_config, "model"):
                    model_cfg = agent_config.model
                elif isinstance(agent_config, dict):
                    model_cfg = agent_config.get("model")

                if model_cfg:
                    if hasattr(model_cfg, "name"):
                        model_name = model_cfg.name
                        temperature = model_cfg.temperature
                        max_tokens = model_cfg.max_tokens
                    elif isinstance(model_cfg, dict):
                        model_name = model_cfg.get("name", model_name)
                        temperature = model_cfg.get("temperature", temperature)
                        max_tokens = model_cfg.get("max_tokens", max_tokens)
                    logger.info(
                        "using_team_model_config",
                        agent="github",
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
        except Exception:
            pass

    return Agent[TaskContext](
        name="GitHubAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=ModelSettings(
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        tools=tools,
        output_type=GitHubAnalysis,
    )
