"""GitHub repository operations agent."""

from agents import Agent, Tool, function_tool

from ..core.agent_builder import create_model_settings
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
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
    Includes both remote GitHub API tools and local git CLI tools.
    """
    tools = [think, llm_call, web_search, ask_human]

    # Remote GitHub API tools (for accessing any GitHub repository)
    try:
        from ..tools.github_tools import (
            close_issue,
            create_branch,
            create_pull_request,
            # Repository info
            get_repo_info,
            github_add_issue_comment,
            github_add_pr_comment,
            github_compare_commits,
            github_create_issue,
            github_create_pr_review,
            github_get_commit,
            github_get_issue,
            github_get_pr,
            github_get_pr_files,
            # Commits
            github_list_commits,
            github_list_contributors,
            github_list_issue_comments,
            github_list_pr_commits,
            github_list_pr_reviews,
            github_list_releases,
            github_list_tags,
            github_search_commits_by_timerange,
            github_search_issues,
            github_search_prs,
            # Branches and tags
            list_branches,
            list_files,
            # Issues
            list_issues,
            # Pull requests
            list_pull_requests,
            list_workflow_runs,
            merge_pull_request,
            read_github_file,
            search_github_code,
            # GitHub Actions
            trigger_workflow,
        )

        tools.extend(
            [
                # Repository info
                get_repo_info,
                list_files,
                read_github_file,
                search_github_code,
                github_list_contributors,
                # Commits
                github_list_commits,
                github_get_commit,
                github_compare_commits,
                github_search_commits_by_timerange,
                # Branches and tags
                list_branches,
                create_branch,
                github_list_tags,
                github_list_releases,
                # Pull requests
                list_pull_requests,
                github_get_pr,
                create_pull_request,
                merge_pull_request,
                github_get_pr_files,
                github_list_pr_commits,
                github_list_pr_reviews,
                github_create_pr_review,
                github_add_pr_comment,
                github_search_prs,
                # Issues
                list_issues,
                github_get_issue,
                github_create_issue,
                close_issue,
                github_list_issue_comments,
                github_add_issue_comment,
                github_search_issues,
                # GitHub Actions
                trigger_workflow,
                list_workflow_runs,
            ]
        )
        logger.debug("github_remote_tools_loaded", count=len(tools) - 3)
    except Exception as e:
        logger.warning("github_tools_load_failed", error=str(e))

    # Local git CLI tools (for working with locally cloned repositories)
    try:
        from ..tools.git_tools import (
            # Commit operations
            git_add,
            git_blame,
            git_branch_create,
            git_branch_delete,
            # Branch operations
            git_branch_list,
            git_checkout,
            git_cherry_pick,
            git_commit,
            git_diff,
            # Remote sync
            git_fetch,
            git_log,
            git_ls_files,
            git_merge,
            git_pull,
            git_push,
            git_reflog,
            git_remote_list,
            git_reset,
            # Utilities
            git_rev_parse,
            git_revert,
            git_shortlog,
            git_show,
            git_stash_apply,
            # Stash operations
            git_stash_list,
            git_stash_pop,
            git_stash_save,
            # Core operations
            git_status,
            git_tag_create,
            # Tags
            git_tag_list,
        )

        tools.extend(
            [
                # Core operations
                git_status,
                git_log,
                git_show,
                git_diff,
                git_blame,
                # Branch operations
                git_branch_list,
                git_branch_create,
                git_branch_delete,
                git_checkout,
                git_merge,
                # Remote sync
                git_fetch,
                git_pull,
                git_push,
                git_remote_list,
                # Commit operations
                git_add,
                git_commit,
                git_reset,
                git_revert,
                git_cherry_pick,
                # Stash operations
                git_stash_list,
                git_stash_save,
                git_stash_pop,
                git_stash_apply,
                # Tags
                git_tag_list,
                git_tag_create,
                # Utilities
                git_rev_parse,
                git_ls_files,
                git_shortlog,
                git_reflog,
            ]
        )
        logger.debug("git_local_tools_loaded")
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
                logger.warning(
                    "tool_wrap_failed",
                    tool=getattr(t, "__name__", str(t)),
                    error=str(e),
                )
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

## CRITICAL: CHOOSING THE RIGHT TOOLS

You have TWO types of tools. Choosing the correct type is essential:

### REMOTE GitHub API Tools (use for ANY repository by name)
Use these when given a repository in "owner/repo" format (e.g., "facebook/react", "kubernetes/kubernetes").
These tools access GitHub's API and work with ANY repository you have access to.

| Tool | Purpose |
|------|---------|
| `github_list_commits` | List recent commits (SIMPLEST way to get commits) |
| `github_get_commit` | Get details of a specific commit |
| `github_compare_commits` | Compare two branches/commits/tags |
| `github_search_commits_by_timerange` | Search commits in a time window |
| `list_pull_requests` | List PRs in a repository |
| `github_get_pr` | Get PR details |
| `github_get_pr_files` | See files changed in a PR |
| `github_list_pr_commits` | List commits in a PR |
| `list_issues` | List issues |
| `github_get_issue` | Get issue details |
| `read_github_file` | Read a file from a remote repo |
| `search_github_code` | Search code across repos |
| `list_branches` | List branches |
| `github_list_tags` | List tags |
| `github_list_releases` | List releases |
| `get_repo_info` | Get repository metadata |
| `github_list_contributors` | List contributors |

### LOCAL Git CLI Tools (use ONLY for locally cloned repositories)
Use these ONLY when working with a repository that exists in the current working directory.
These run `git` commands locally and will FAIL if the repo isn't cloned.

| Tool | Purpose |
|------|---------|
| `git_log` | View local commit history |
| `git_show` | View commit details locally |
| `git_diff` | Compare local changes |
| `git_status` | Check local repo status |
| `git_blame` | See line-by-line history |
| `git_branch_list` | List local branches |
| `git_stash_list` | List stashes |
| `git_reflog` | View HEAD history |

### HOW TO DECIDE

```
User asks about "owner/repo" format (e.g., "incidentfox/incidentfox")
  → Use REMOTE tools (github_list_commits, list_pull_requests, etc.)

User asks about current directory or local repo
  → Use LOCAL tools (git_log, git_status, etc.)

User asks "list recent commits in X repo"
  → Use github_list_commits(repo="owner/repo") - NOT git_log!

User asks "what changed locally"
  → Use git_status, git_diff
```

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

## INVESTIGATION METHODOLOGY

### For Incident Investigation
1. Identify the affected service/repository
2. Use `github_list_commits` to check recent commits
3. Use `list_pull_requests` to find PRs merged around the incident time
4. Use `github_search_issues` for related issues or known problems
5. Use `read_github_file` to examine relevant code

### For Code Context
1. Use `list_files` to find relevant files/modules
2. Use `read_github_file` to read the current state
3. Use `github_list_commits` with path filter to check recent changes
4. Use `list_pull_requests` for related PRs

## COMMON PATTERNS

| Scenario | First Tool | Follow-up |
|----------|------------|-----------|
| "List commits in owner/repo" | `github_list_commits` | `github_get_commit` for details |
| "Recent PRs in owner/repo" | `list_pull_requests` | `github_get_pr_files` |
| "What changed locally" | `git_status` | `git_diff` |
| "Compare branches" | `github_compare_commits` | - |
| "Find code pattern" | `search_github_code` | `read_github_file` |

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
    from ..prompts.layers import (
        apply_role_based_prompt,
        build_agent_prompt_sections,
        build_tool_guidance,
    )

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

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    # Uses predefined GITHUB_ERRORS from registry
    shared_sections = build_agent_prompt_sections(
        integration_name="github",
        is_subagent=is_subagent,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

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
                        reasoning = getattr(model_cfg, "reasoning", None)
                        verbosity = getattr(model_cfg, "verbosity", None)
                    elif isinstance(model_cfg, dict):
                        model_name = model_cfg.get("name", model_name)
                        temperature = model_cfg.get("temperature", temperature)
                        max_tokens = model_cfg.get("max_tokens", max_tokens)
                        reasoning = model_cfg.get("reasoning")
                        verbosity = model_cfg.get("verbosity")
                    logger.info(
                        "using_team_model_config",
                        agent="github",
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning=reasoning,
                        verbosity=verbosity,
                    )
        except Exception:
            pass

    return Agent[TaskContext](
        name="GitHubAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=create_model_settings(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            verbosity=verbosity,
        ),
        tools=tools,
        output_type=GitHubAnalysis,
    )
