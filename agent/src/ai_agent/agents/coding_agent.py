"""Code analysis, bug fixing, and code generation agent."""

from agents import Agent, Tool, function_tool

from ..core.agent_builder import create_model_settings
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


def _load_coding_tools():
    """Load coding-specific tools."""
    tools = [think, llm_call, web_search, ask_human]

    # Coding tools (file ops, search, testing)
    try:
        from ..tools.coding_tools import (
            list_directory,
            pytest_run,
            python_run_tests,
            read_file,
            repo_search_text,
            run_linter,
            write_file,
        )

        tools.extend(
            [
                repo_search_text,
                read_file,
                write_file,
                list_directory,
                python_run_tests,
                pytest_run,
                run_linter,
            ]
        )
    except Exception as e:
        logger.warning("coding_tools_load_failed", error=str(e))

    # Git tools
    try:
        from ..tools.git_tools import (
            git_blame,
            git_branch_list,
            git_diff,
            git_log,
            git_show,
            git_status,
        )

        tools.extend(
            [
                git_status,
                git_diff,
                git_log,
                git_blame,
                git_show,
                git_branch_list,
            ]
        )
    except Exception as e:
        logger.warning("git_tools_load_failed", error=str(e))

    # Note: GitHub tools moved to dedicated github_agent.py
    # Coding agent focuses on local code analysis and testing

    # Wrap plain functions into Tool objects for SDK compatibility
    wrapped = []
    for t in tools:
        if isinstance(t, Tool) or hasattr(t, "name"):
            wrapped.append(t)
        else:
            try:
                wrapped.append(function_tool(t, strict_mode=False))
            except TypeError:
                wrapped.append(function_tool(t))
            except Exception as e:
                logger.warning(
                    "tool_wrap_failed",
                    tool=getattr(t, "__name__", str(t)),
                    error=str(e),
                )
                wrapped.append(t)
    return wrapped


class CodeChange(BaseModel):
    """A code change recommendation."""

    file_path: str
    change_type: str  # fix, refactor, optimize, add
    description: str
    code_snippet: str


class CodingAnalysis(BaseModel):
    """Code analysis result."""

    summary: str = Field(description="Analysis summary")
    issues_found: list[str] = Field(description="Issues identified in code")
    code_changes: list[CodeChange] = Field(description="Recommended code changes")
    testing_recommendations: list[str] = Field(description="Testing suggestions")
    explanation: str = Field(description="Detailed explanation of changes")


def create_coding_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create coding expert agent.

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
                   Can also be set via team config: agents.coding.is_master: true
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
        agent_config = team_cfg.get_agent_config("coding_agent")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info(
                    "using_custom_coding_prompt", prompt_length=len(custom_prompt)
                )

    base_prompt = (
        custom_prompt
        or """You are an expert software engineer specializing in code analysis, debugging, and fixes.

## YOUR ROLE

You are a specialized code investigator. Your job is to analyze code, identify bugs, understand behavior, and suggest fixes or improvements.

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty
- **Never fabricate code** - Only show code you actually read from files
- **Acknowledge uncertainty** - If you're not sure about behavior, say so
- **Distinguish facts from hypotheses** - "The function returns null on line 45 (fact). This could cause the NullPointerException (hypothesis)."

### Thoroughness
- **Understand before fixing** - Read and comprehend the code before suggesting changes
- **Follow the call chain** - Trace errors to their source
- **Consider side effects** - Will your fix break something else?

### Evidence Presentation
- **Quote actual code** - Include file paths and line numbers
- **Explain your reasoning** - Why is this the bug? Why is this the fix?
- **Show context** - Include enough surrounding code to understand the change

### Safety
- **Test your fixes** - Run tests to verify changes work
- **Don't introduce new bugs** - Be careful with changes
- **Consider edge cases** - What happens with null, empty, or unexpected input?

## YOUR TOOLS

You have access to powerful tools for code investigation:

**File Operations:**
- `read_file` - Read source code files
- `write_file` - Write/update files
- `list_directory` - Explore project structure
- `repo_search_text` - Search code with regex patterns

**Testing:**
- `python_run_tests` - Run unittest discovery
- `pytest_run` - Run pytest with custom args
- `run_linter` - Check code quality (ruff, flake8, eslint)

**Git:**
- `git_status` - Check repository state
- `git_diff` - See changes
- `git_log` - View commit history
- `git_blame` - Find who changed what
- `git_show` - View specific commits

**Reasoning:**
- `think` - Internal reasoning (use for complex analysis)
- `llm_call` - Get additional AI perspective
- `web_search` - Search for documentation/solutions

## INVESTIGATION PROCESS

1. **Explore** - Use `list_directory` and `repo_search_text` to understand the codebase
2. **Read** - Use `read_file` to examine relevant code
3. **Analyze** - Use `think` to reason about the problem
4. **Check History** - Use `git_log` and `git_diff` to see recent changes
5. **Test** - Run tests to verify current state
6. **Fix** - Use `write_file` to apply fixes
7. **Verify** - Run tests again to confirm fix works

## CODE QUALITY PRINCIPLES

- **Correctness**: Fix must solve the problem
- **Safety**: Don't introduce new bugs
- **Performance**: Consider efficiency
- **Maintainability**: Keep code readable
- **Testing**: Always verify with tests

## COMMON BUG PATTERNS

- **Null/undefined errors**: Add null checks
- **Race conditions**: Use proper synchronization
- **Memory leaks**: Clean up resources
- **Off-by-one errors**: Check array bounds
- **Exception handling**: Catch and handle errors properly

When providing fixes:
- Show exact file paths and line numbers
- Provide complete code with context
- Explain what changed and why
- Run tests to verify the fix"""
    )

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="coding",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load coding-specific tools
    tools = _load_coding_tools()
    logger.info("coding_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    # Uses predefined CODING_ERRORS from registry
    shared_sections = build_agent_prompt_sections(
        integration_name="coding",
        is_subagent=is_subagent,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.4
    max_tokens = config.openai.max_tokens

    if team_cfg:
        agent_config = team_cfg.get_agent_config("coding")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            logger.info(
                "using_team_model_config",
                agent="coding",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    return Agent[TaskContext](
        name="CodingAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=create_model_settings(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        tools=tools,
        output_type=CodingAnalysis,
    )
