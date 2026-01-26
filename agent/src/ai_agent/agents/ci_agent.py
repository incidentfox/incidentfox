"""CI/CD failure analysis and auto-fix agent.

This agent specializes in:
- Analyzing CI/CD pipeline failures (GitHub Actions, CodePipeline, etc.)
- Debugging test failures (Jest, Cypress, pytest, etc.)
- Generating and committing fixes automatically
- Posting analysis and fix reports to PR comments
"""

from typing import Any

from agents import Agent, function_tool

from ..core.agent_builder import create_model_settings
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


def _load_ci_tools():
    """Load CI-specific tools."""
    tools = [think, llm_call, ask_human]

    # CI tools (workflow logs, PR comments, commits)
    try:
        from ..tools.ci_tools import (
            commit_file_changes,
            download_workflow_run_logs,
            get_file_content,
            get_pr_comments,
            get_workflow_run_info,
            list_failed_workflow_runs,
            list_repo_directory,
            post_pr_comment,
            update_or_create_pr_comment,
        )

        # Wrap raw functions with function_tool for agent use
        tools.extend(
            [
                function_tool(download_workflow_run_logs),
                function_tool(get_workflow_run_info),
                function_tool(list_failed_workflow_runs),
                function_tool(post_pr_comment),
                function_tool(get_pr_comments),
                function_tool(update_or_create_pr_comment),
                function_tool(commit_file_changes),
                function_tool(get_file_content),
                function_tool(list_repo_directory),
            ]
        )
    except Exception as e:
        logger.warning("ci_tools_load_failed", error=str(e))

    # GitHub tools for additional context (raw functions - need wrapping)
    try:
        from ..tools.github_tools import (
            list_files,
            list_pull_requests,
            list_workflow_runs,
            read_github_file,
        )

        tools.extend(
            [
                function_tool(list_pull_requests),
                function_tool(list_workflow_runs),
                function_tool(read_github_file),
                function_tool(list_files),
            ]
        )
    except Exception as e:
        logger.warning("github_tools_load_failed", error=str(e))

    # Coding tools for file analysis (already decorated - use directly)
    try:
        from ..tools.coding_tools import (
            list_directory,
            read_file,
        )

        # These are already FunctionTool objects from @function_tool decorator
        tools.extend([read_file, list_directory])
    except Exception as e:
        logger.warning("coding_tools_load_failed", error=str(e))

    return tools


class CIAnalysisResult(BaseModel):
    """Result of CI failure analysis."""

    summary: str = Field(description="Brief summary of the failure")
    root_cause: str = Field(description="Root cause analysis with evidence")
    framework: str = Field(
        description="Detected test framework (jest, cypress, pytest, etc.)"
    )
    failed_tests: list[str] = Field(description="List of failed test names")
    affected_files: list[str] = Field(description="Files involved in the failure")
    recommendations: list[str] = Field(description="Recommended actions to fix")


class CIFixResult(BaseModel):
    """Result of CI fix generation."""

    description: str = Field(description="Description of the fix")
    reasoning: str = Field(description="Explanation of why this fix works")
    confidence: str = Field(description="Confidence level: high, medium, low")
    file_changes: dict[str, str] = Field(description="Dict of file_path -> new_content")
    warnings: list[str] = Field(description="Any warnings or caveats")


class CIAgentOutput(BaseModel):
    """Complete CI agent output."""

    analysis: CIAnalysisResult = Field(description="Failure analysis")
    fix: CIFixResult | None = Field(description="Proposed fix if applicable")
    comment_posted: bool = Field(description="Whether PR comment was posted")
    fix_committed: bool = Field(description="Whether fix was committed")
    commit_sha: str | None = Field(description="Commit SHA if fix was committed")


CI_AGENT_PROMPT = """You are an expert CI/CD engineer and debugging specialist.

## YOUR MISSION

You analyze CI/CD pipeline failures, identify root causes, and generate automatic fixes.

## YOUR TOOLS

**Workflow Analysis:**
- `download_workflow_run_logs` - Get full CI logs from GitHub Actions
- `get_workflow_run_info` - Get workflow run metadata
- `list_failed_workflow_runs` - Find recent failures

**Repository Access:**
- `get_file_content` - Read files from the repository
- `list_repo_directory` - Explore repository structure
- `read_github_file` - Read files from GitHub

**PR Interaction:**
- `get_pr_comments` - Read PR discussion for context
- `post_pr_comment` - Post analysis comment
- `update_or_create_pr_comment` - Update sticky bot comment

**Fixes:**
- `commit_file_changes` - Commit fixes to branch
- `llm_call` - Get additional analysis perspective

**Reasoning:**
- `think` - Internal reasoning for complex analysis

## INVESTIGATION PROCESS (FOLLOW ALL STEPS!)

1. **Download Logs** - Use `download_workflow_run_logs` to get full CI output
2. **Identify Framework** - Detect if it's Jest, Cypress, pytest, etc.
3. **Find Failure** - Locate the specific test/assertion that failed

**CRITICAL - DO NOT SKIP THESE STEPS:**

4. **EXPLORE THE REPO FIRST** - Use `list_repo_directory` to find actual file paths:
   - Start with `list_repo_directory(repo, "")` to see top-level structure
   - Navigate into directories: `list_repo_directory(repo, "frontend")`, etc.
   
   **CRITICAL: ONLY use file paths that you SEE in the directory listing results!**
   Do NOT guess paths like "frontend/pages/api/data.js" - check the listing first!

5. **READ THE ACTUAL CODE** - Use `get_file_content` with EXACT paths from step 4:
   - If error mentions "/api/data", find where API calls are made
   - Typical locations: `utils/`, `lib/`, `api/`, `services/` folders
   - Read the backend routes file (usually in `routes/`, `api/`)
   - Find the EXACT line of code that needs to change

6. **Trace the Issue** - Example for "404 on /api/data":
   - List `frontend/` → find `utils/api.ts` exists
   - Read `frontend/utils/api.ts` → find `getData: () => fetchFromAPI('api/data')`
   - List `backend/` → find `routes/index.js` exists  
   - Read `backend/routes/index.js` → find `router.get('/records', ...)`
   - **MISMATCH FOUND**: Frontend calls `/api/data`, backend has `/api/records`

7. **Analyze Root Cause** - Use `think` to connect the dots
8. **Generate SPECIFIC Fix** - State exactly: "Change file X, line Y, from A to B"
9. **Commit & Report** - Use `commit_file_changes` and `post_pr_comment`

**DO NOT just describe symptoms. Find and state the EXACT fix needed.**

## COMMON CI FAILURE PATTERNS

### Test Failures
- **Assertion mismatch**: Expected vs actual values differ
- **Timeout**: Async operations not completing
- **Missing mocks**: External services not stubbed
- **Race conditions**: Flaky timing-dependent tests

### Build Failures
- **Missing dependencies**: Package not installed
- **Type errors**: TypeScript/compile-time issues
- **Import errors**: Wrong paths or missing exports

### Environment Issues
- **Missing env vars**: Required config not set
- **Port conflicts**: Service already running
- **Docker issues**: Image build or container problems

## FIX GENERATION PRINCIPLES

1. **Minimal Change**: Only modify what's necessary
2. **Complete Content**: Provide full file content, not diffs
3. **Verify Logic**: Ensure fix addresses the actual root cause
4. **Consider Side Effects**: Note any potential impacts
5. **Set Confidence**: Be honest about certainty level
   - `high`: Clear issue, straightforward fix
   - `medium`: Reasonable fix but verify
   - `low`: Uncertain, needs human review

## OUTPUT FORMAT

Always provide:
1. **Summary**: One-line description of the issue
2. **Root Cause**: Detailed explanation with evidence FROM READING THE ACTUAL CODE
3. **Specific Fix**: EXACT file path, line number, and code change (before → after)
4. **Verification**: How to confirm the fix works

**BAD output**: "Check if the API endpoint is correct"
**GOOD output**: "Change frontend/utils/api.ts line 50: `getData: () => fetchFromAPI('api/data')` → `getData: () => fetchFromAPI('api/records')`"

## EXAMPLE ANALYSIS

```
📋 Summary: Cypress test failing - API endpoint mismatch

🔍 Root Cause:
The test expects data from `/api/data` but the backend only exposes `/api/records`.

Evidence:
- frontend/utils/api.ts:50 calls `/api/data`
- backend/routes/index.js:7 defines `/api/records`
- Test timeout after 30s waiting for "Example record A"

✅ Recommended Fix:
Change frontend/utils/api.ts line 50:
- getData: () => fetchFromAPI('api/data'),
+ getData: () => fetchFromAPI('api/records'),

🧪 Verification:
Run `npm run cypress:run` locally or push to trigger CI.
```

When providing fixes, be precise, technical, and actionable."""


def create_ci_agent(team_config: dict[str, Any] | None = None) -> Agent[TaskContext]:
    """Create CI/CD expert agent.

    Args:
        team_config: Optional team-specific configuration

    Returns:
        Configured CI Agent
    """
    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        agent_config = team_cfg.get_agent_config("ci_agent")
        if agent_config and agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info("using_custom_ci_prompt", prompt_length=len(custom_prompt))

    system_prompt = custom_prompt or CI_AGENT_PROMPT

    # Load CI-specific tools
    tools = _load_ci_tools()
    logger.info("ci_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    from ..prompts.layers import build_tool_guidance

    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3  # Lower temp for precision
    max_tokens = config.openai.max_tokens

    if team_cfg:
        agent_config = team_cfg.get_agent_config("ci")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            logger.info(
                "using_team_model_config",
                agent="ci",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    # Note: We don't use output_type because Dict fields aren't compatible with
    # strict JSON schema in the OpenAI Agents SDK. The agent returns text output
    # which we parse for the PR comment.
    return Agent[TaskContext](
        name="CIAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=create_model_settings(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        tools=tools,
    )


# ============================================================================
# Helper Functions for CI Workflows
# ============================================================================


def format_ci_analysis_comment(
    analysis: CIAnalysisResult,
    run_id: int,
    run_url: str,
    head_sha: str,
) -> str:
    """Format CI analysis as a GitHub PR comment."""
    recommendations = "\n".join([f"- {r}" for r in analysis.recommendations])
    failed_tests = "\n".join([f"- `{t}`" for t in analysis.failed_tests]) or "N/A"
    affected_files = ", ".join([f"`{f}`" for f in analysis.affected_files]) or "N/A"

    return f"""<!-- incidentfox-ci-analysis -->
## 🦊 IncidentFox CI Failure Analysis

**Status:** ❌ CI Failed

### 📋 Summary
{analysis.summary}

### 🔍 Root Cause Analysis
{analysis.root_cause}

### 📁 Details
- **Framework:** {analysis.framework}
- **Failed Tests:** {failed_tests}
- **Affected Files:** {affected_files}

### ✅ Recommended Actions
{recommendations}

---

**🎯 Quick Actions**

Reply with `fix`, `approve`, or `lgtm` to automatically generate and apply a fix.

Other commands:
- `/incidentfox show logs` - Show detailed logs
- `/incidentfox analyze` - Re-run analysis

---

**CI Run Details**
- Run ID: [{run_id}]({run_url})
- Commit: `{head_sha[:8]}`

*🦊 Powered by IncidentFox*
"""


def format_ci_fix_comment(
    fix: CIFixResult,
    commit_sha: str,
    repo: str,
) -> str:
    """Format CI fix result as a GitHub PR comment."""
    files_changed = "\n".join([f"- `{f}`" for f in fix.file_changes.keys()])
    warnings_text = ""
    if fix.warnings:
        warnings_text = "\n\n**⚠️ Warnings:**\n" + "\n".join(
            [f"- {w}" for w in fix.warnings]
        )

    confidence_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(
        fix.confidence, "⚪"
    )

    return f"""## ✅ CI Fix Applied Successfully

{confidence_emoji} **Confidence:** {fix.confidence.title()}

**Changes:**
{files_changed}

**Reasoning:**
{fix.reasoning}
{warnings_text}

**Commit:** [`{commit_sha[:8]}`](https://github.com/{repo}/commit/{commit_sha})

GitHub Actions should rerun checks automatically for the updated PR commit.

---
*🦊 Powered by IncidentFox*
"""
