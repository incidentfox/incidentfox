"""
OpenHands SDK Provider for SRE Agent.

This module implements the LLMProvider interface using OpenHands SDK,
enabling multi-LLM support (Claude, Gemini, OpenAI, etc.) with full
feature parity to the Claude SDK provider.

Features:
- Multi-LLM support via LiteLLM (Gemini, OpenAI, Claude)
- Skills system: Auto-discovers and loads skills from .claude/skills/
- Subagents: Isolated context execution for log-analyst, k8s-debugger, remediator
- Image support: Multimodal input for supported models
- Tool output capture: Streams tool results back to caller
- Conversation history persistence across turns
- Observability via Laminar @observe() decorator
- WebSearch/WebFetch tools for web access
"""

import asyncio
import html
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

import httpx
import yaml
from events import (
    StreamEvent,
    error_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)
from lmnr import observe

from providers.base import LLMProvider, ProviderConfig, SubagentConfig

logger = logging.getLogger(__name__)


# =============================================================================
# Skills System
# =============================================================================


class SkillLoader:
    """
    Loads and manages skills from .claude/skills/ directory.

    Skills are markdown files with YAML frontmatter that provide
    domain-specific knowledge and methodologies to the agent.
    """

    def __init__(self, skills_dir: str):
        """
        Initialize skill loader.

        Args:
            skills_dir: Path to .claude/skills/ directory
        """
        self.skills_dir = Path(skills_dir)
        self._skills_cache: dict[str, dict] = {}
        self._discover_skills()

    def _discover_skills(self) -> None:
        """Discover all available skills from the skills directory."""
        if not self.skills_dir.exists():
            logger.warning(f"[Skills] Skills directory not found: {self.skills_dir}")
            return

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    try:
                        skill_data = self._parse_skill_file(skill_file)
                        if skill_data:
                            self._skills_cache[skill_data["name"]] = skill_data
                            logger.debug(f"[Skills] Discovered: {skill_data['name']}")
                    except Exception as e:
                        logger.warning(f"[Skills] Failed to parse {skill_file}: {e}")

        logger.info(f"[Skills] Discovered {len(self._skills_cache)} skills")

    def _parse_skill_file(self, skill_file: Path) -> Optional[dict]:
        """
        Parse a skill markdown file with YAML frontmatter.

        Args:
            skill_file: Path to SKILL.md file

        Returns:
            Dict with name, description, content, and dir_path
        """
        content = skill_file.read_text()

        # Parse YAML frontmatter (between --- markers)
        frontmatter_match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL
        )

        if not frontmatter_match:
            # No frontmatter, use directory name as skill name
            return {
                "name": skill_file.parent.name,
                "description": f"Skill from {skill_file.parent.name}",
                "content": content,
                "dir_path": str(skill_file.parent),
            }

        try:
            frontmatter = yaml.safe_load(frontmatter_match.group(1))
            body = frontmatter_match.group(2)

            return {
                "name": frontmatter.get("name", skill_file.parent.name),
                "description": frontmatter.get("description", ""),
                "content": body,
                "dir_path": str(skill_file.parent),
            }
        except yaml.YAMLError as e:
            logger.warning(f"[Skills] YAML parse error in {skill_file}: {e}")
            return None

    def get_skill_summaries(self) -> str:
        """
        Get a summary of all available skills for the system prompt.

        Returns:
            Formatted string listing all skills with descriptions
        """
        if not self._skills_cache:
            return "No skills available."

        lines = ["## Available Skills\n"]
        lines.append("Use the appropriate skill for domain-specific tasks:\n")

        for name, skill in sorted(self._skills_cache.items()):
            lines.append(f"- **{name}**: {skill['description']}")

        lines.append("\nTo use a skill, read its content from the skills directory.")
        return "\n".join(lines)

    def get_skill(self, name: str) -> Optional[dict]:
        """
        Get a specific skill by name.

        Args:
            name: Skill name

        Returns:
            Skill dict or None if not found
        """
        return self._skills_cache.get(name)

    def list_skills(self) -> list[str]:
        """Get list of all skill names."""
        return list(self._skills_cache.keys())


# =============================================================================
# Subagent System
# =============================================================================


class SubagentExecutor:
    """
    Manages isolated subagent execution for context separation.

    Subagents run in isolated contexts to prevent large outputs
    (like log dumps) from polluting the main conversation context.
    """

    def __init__(
        self,
        config: SubagentConfig,
        model: str,
        api_key: str,
        workspace_dir: str,
        skills_loader: Optional[SkillLoader] = None,
    ):
        """
        Initialize subagent executor.

        Args:
            config: Subagent configuration
            model: LLM model to use
            api_key: API key for the model
            workspace_dir: Working directory
            skills_loader: Optional skill loader for skill access
        """
        self.config = config
        self.model = model
        self.api_key = api_key
        self.workspace_dir = workspace_dir
        self.skills_loader = skills_loader
        self._is_running = False

    async def execute(
        self,
        task_prompt: str,
        thread_id: str,
    ) -> AsyncIterator[StreamEvent]:
        """
        Execute a task in the subagent's isolated context.

        Args:
            task_prompt: The task to execute
            thread_id: Parent thread ID for event tracking

        Yields:
            StreamEvent objects for subagent actions
        """
        self._is_running = True

        try:
            # Build subagent system prompt
            system_prompt = self._build_system_prompt()

            # Use LiteLLM for multi-model support
            import litellm

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_prompt},
            ]

            yield thought_event(
                thread_id,
                f"[Subagent:{self.config.name}] Starting task...",
            )

            # Execute with tool use loop
            max_iterations = 20  # Prevent infinite loops
            iteration = 0
            final_response = ""

            while iteration < max_iterations and self._is_running:
                iteration += 1

                try:
                    response = await litellm.acompletion(
                        model=self.model,
                        messages=messages,
                        api_key=self.api_key,
                        tools=self._get_tools_schema(),
                        tool_choice="auto",
                    )

                    assistant_message = response.choices[0].message
                    messages.append(assistant_message.model_dump())

                    # Check if there are tool calls
                    if assistant_message.tool_calls:
                        for tool_call in assistant_message.tool_calls:
                            tool_name = tool_call.function.name
                            tool_args = tool_call.function.arguments

                            # Parse arguments
                            import json

                            try:
                                args = json.loads(tool_args) if tool_args else {}
                            except json.JSONDecodeError:
                                args = {"raw": tool_args}

                            yield tool_start_event(
                                thread_id,
                                tool_name,
                                args,
                            )

                            # Execute tool
                            tool_result = await self._execute_tool(tool_name, args)

                            yield tool_end_event(
                                thread_id,
                                tool_name,
                                success=not tool_result.get("error"),
                                output=tool_result.get("output", "")[:5000],
                            )

                            # Add tool result to messages
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": tool_result.get("output", ""),
                                }
                            )
                    else:
                        # No tool calls - we have a final response
                        final_response = assistant_message.content or ""
                        if final_response:
                            yield thought_event(thread_id, final_response)
                        break

                except Exception as e:
                    logger.error(f"[Subagent:{self.config.name}] Error: {e}")
                    yield error_event(
                        thread_id,
                        f"Subagent error: {str(e)}",
                        recoverable=True,
                    )
                    break

            if iteration >= max_iterations:
                yield thought_event(
                    thread_id,
                    f"[Subagent:{self.config.name}] Reached iteration limit",
                )

        finally:
            self._is_running = False

    def _build_system_prompt(self) -> str:
        """Build system prompt for the subagent."""
        prompt_parts = [self.config.prompt]

        # Add skill information if available
        if self.skills_loader:
            prompt_parts.append("\n\n" + self.skills_loader.get_skill_summaries())

        prompt_parts.append(f"\n\nWorking directory: {self.workspace_dir}")

        return "\n".join(prompt_parts)

    def _get_tools_schema(self) -> list[dict]:
        """Get OpenAI-compatible tools schema for the subagent."""
        tools = []

        if "Bash" in self.config.tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "description": "Execute a bash command",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "The bash command to execute",
                                },
                            },
                            "required": ["command"],
                        },
                    },
                }
            )

        if "Read" in self.config.tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read contents of a file",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Path to the file to read",
                                },
                            },
                            "required": ["path"],
                        },
                    },
                }
            )

        if "Glob" in self.config.tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "glob",
                        "description": "Find files matching a pattern",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {
                                    "type": "string",
                                    "description": "Glob pattern (e.g., '**/*.py')",
                                },
                            },
                            "required": ["pattern"],
                        },
                    },
                }
            )

        if "Grep" in self.config.tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "grep",
                        "description": "Search for text in files",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {
                                    "type": "string",
                                    "description": "Search pattern (regex)",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Path to search in",
                                },
                            },
                            "required": ["pattern"],
                        },
                    },
                }
            )

        return tools

    async def _execute_tool(self, tool_name: str, args: dict) -> dict:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool
            args: Tool arguments

        Returns:
            Dict with 'output' and optionally 'error'
        """
        try:
            if tool_name == "bash":
                command = args.get("command", "")
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=self.workspace_dir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR:\n{result.stderr}"
                if result.returncode != 0:
                    output += f"\nExit code: {result.returncode}"
                return {"output": output}

            elif tool_name == "read_file":
                path = args.get("path", "")
                full_path = Path(self.workspace_dir) / path
                if not full_path.exists():
                    return {"output": f"File not found: {path}", "error": True}
                content = full_path.read_text()
                return {"output": content}

            elif tool_name == "glob":
                pattern = args.get("pattern", "*")
                import glob as glob_module

                matches = glob_module.glob(
                    str(Path(self.workspace_dir) / pattern),
                    recursive=True,
                )
                # Make paths relative
                rel_matches = [
                    str(Path(m).relative_to(self.workspace_dir)) for m in matches
                ]
                return {"output": "\n".join(rel_matches[:100])}

            elif tool_name == "grep":
                pattern = args.get("pattern", "")
                path = args.get("path", ".")
                result = subprocess.run(
                    ["grep", "-r", "-n", pattern, path],
                    cwd=self.workspace_dir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return {"output": result.stdout or "(no matches)"}

            else:
                return {"output": f"Unknown tool: {tool_name}", "error": True}

        except subprocess.TimeoutExpired:
            return {"output": "Command timed out", "error": True}
        except Exception as e:
            return {"output": f"Tool error: {str(e)}", "error": True}

    def stop(self) -> None:
        """Stop the subagent execution."""
        self._is_running = False


# =============================================================================
# Main Provider
# =============================================================================


class OpenHandsProvider(LLMProvider):
    """
    LLM Provider using LiteLLM for multi-model support.

    Provides feature parity with Claude SDK:
    - Skills: Auto-loaded from .claude/skills/
    - Subagents: Isolated context execution
    - Images: Multimodal support for compatible models
    - Tools: Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Task

    Supported models (via LiteLLM):
    - anthropic/claude-sonnet-4-20250514
    - gemini/gemini-2.0-flash
    - openai/gpt-5.2
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

        # LLM configuration
        self._model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-20250514")
        self._api_key = self._get_api_key()

        # Components
        self._skills_loader: Optional[SkillLoader] = None
        self._subagent_executors: dict[str, SubagentExecutor] = {}
        self._conversation_history: list[dict] = []
        self._is_running = False

        # For answer handling (not fully implemented per user request)
        self._pending_answer_event: Optional[asyncio.Event] = None
        self._pending_answer: Optional[dict] = None

    def _get_api_key(self) -> str:
        """Get API key based on model provider."""
        model = self._model.lower()
        if model.startswith("anthropic/"):
            return os.getenv("ANTHROPIC_API_KEY", "")
        elif model.startswith("gemini/"):
            return os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
        elif model.startswith("openai/"):
            return os.getenv("OPENAI_API_KEY", "")
        else:
            return os.getenv("LLM_API_KEY", "")

    async def start(self) -> None:
        """Initialize the provider."""
        # Load skills
        skills_dir = Path(self.config.cwd) / ".claude" / "skills"
        if skills_dir.exists():
            self._skills_loader = SkillLoader(str(skills_dir))
        else:
            logger.warning(f"[OpenHands] Skills directory not found: {skills_dir}")

        # Initialize subagent executors
        for name, subagent_config in self.config.subagents.items():
            # Map subagent model to LiteLLM format
            subagent_model = self._map_subagent_model(subagent_config.model)

            self._subagent_executors[name] = SubagentExecutor(
                config=subagent_config,
                model=subagent_model,
                api_key=self._api_key,
                workspace_dir=self.config.cwd,
                skills_loader=self._skills_loader,
            )

        logger.info(f"[OpenHands] Provider initialized with model: {self._model}")
        logger.info(
            f"[OpenHands] Skills loaded: {self._skills_loader.list_skills() if self._skills_loader else []}"
        )
        logger.info(f"[OpenHands] Subagents: {list(self._subagent_executors.keys())}")

    def _map_subagent_model(self, model_name: str) -> str:
        """Map Claude SDK model names to LiteLLM format."""
        model_mapping = {
            "sonnet": self._model,  # Use same model as parent
            "opus": (
                self._model.replace("sonnet", "opus")
                if "sonnet" in self._model
                else self._model
            ),
            "haiku": (
                self._model.replace("sonnet", "haiku")
                if "sonnet" in self._model
                else self._model
            ),
        }
        return model_mapping.get(model_name, self._model)

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with skills and context."""
        parts = [
            "You are an AI SRE (Site Reliability Engineering) agent.",
            "Your job is to investigate incidents, analyze logs, debug infrastructure issues,",
            "and help with remediation.",
            "",
            "## Core Principles",
            "- Always investigate before acting",
            "- Use dry-run mode for dangerous operations",
            "- Report findings clearly and concisely",
            "- Use subagents for isolated deep-dive analysis",
            "",
        ]

        # Add skills summary
        if self._skills_loader:
            parts.append(self._skills_loader.get_skill_summaries())
            parts.append("")

        # Add subagent information
        if self._subagent_executors:
            parts.append("## Available Subagents")
            parts.append("Use the 'task' tool to spawn subagents for isolated work:")
            for name, executor in self._subagent_executors.items():
                parts.append(f"- **{name}**: {executor.config.description}")
            parts.append("")

        parts.append(f"Working directory: {self.config.cwd}")

        return "\n".join(parts)

    def _get_tools_schema(self) -> list[dict]:
        """Get OpenAI-compatible tools schema."""
        tools = []

        # Bash tool
        if "Bash" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "description": "Execute a bash command. Use for running scripts, kubectl, aws cli, etc.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "The bash command to execute",
                                },
                                "timeout": {
                                    "type": "integer",
                                    "description": "Timeout in seconds (default: 120)",
                                },
                            },
                            "required": ["command"],
                        },
                    },
                }
            )

        # Read tool
        if "Read" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read the contents of a file",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Path to the file",
                                },
                                "offset": {
                                    "type": "integer",
                                    "description": "Line number to start from (1-indexed)",
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Number of lines to read",
                                },
                            },
                            "required": ["path"],
                        },
                    },
                }
            )

        # Write tool
        if "Write" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Write content to a file (overwrites existing)",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Path to the file",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Content to write",
                                },
                            },
                            "required": ["path", "content"],
                        },
                    },
                }
            )

        # Edit tool
        if "Edit" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "edit_file",
                        "description": "Edit a file by replacing text",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Path to the file",
                                },
                                "old_string": {
                                    "type": "string",
                                    "description": "Text to find and replace",
                                },
                                "new_string": {
                                    "type": "string",
                                    "description": "Replacement text",
                                },
                            },
                            "required": ["path", "old_string", "new_string"],
                        },
                    },
                }
            )

        # Glob tool
        if "Glob" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "glob",
                        "description": "Find files matching a glob pattern",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {
                                    "type": "string",
                                    "description": "Glob pattern (e.g., '**/*.py', 'logs/*.log')",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Base path to search from",
                                },
                            },
                            "required": ["pattern"],
                        },
                    },
                }
            )

        # Grep tool
        if "Grep" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "grep",
                        "description": "Search for text patterns in files",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {
                                    "type": "string",
                                    "description": "Search pattern (regex supported)",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "File or directory to search",
                                },
                                "context": {
                                    "type": "integer",
                                    "description": "Lines of context around matches",
                                },
                            },
                            "required": ["pattern"],
                        },
                    },
                }
            )

        # Task tool (subagent spawning)
        if "Task" in self.config.allowed_tools and self._subagent_executors:
            subagent_names = list(self._subagent_executors.keys())
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "task",
                        "description": f"Spawn a subagent for isolated work. Available: {', '.join(subagent_names)}",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "subagent": {
                                    "type": "string",
                                    "description": f"Subagent to use: {', '.join(subagent_names)}",
                                    "enum": subagent_names,
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "Task description for the subagent",
                                },
                            },
                            "required": ["subagent", "prompt"],
                        },
                    },
                }
            )

        # Skill tool
        if "Skill" in self.config.allowed_tools and self._skills_loader:
            skill_names = self._skills_loader.list_skills()
            if skill_names:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": "skill",
                            "description": f"Load a skill for domain-specific guidance. Available: {', '.join(skill_names)}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": f"Skill to load: {', '.join(skill_names)}",
                                    },
                                },
                                "required": ["name"],
                            },
                        },
                    }
                )

        # WebSearch tool
        if "WebSearch" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web for information. Returns search results with titles, URLs, and snippets.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query",
                                },
                                "num_results": {
                                    "type": "integer",
                                    "description": "Number of results to return (default: 5, max: 10)",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            )

        # WebFetch tool
        if "WebFetch" in self.config.allowed_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "description": "Fetch content from a URL and convert HTML to readable text. Use for reading documentation, articles, or web pages.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "URL to fetch",
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "Optional: What information to extract from the page",
                                },
                            },
                            "required": ["url"],
                        },
                    },
                }
            )

        return tools

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
        thread_id: str,
    ) -> AsyncIterator[tuple[str, bool, Optional[str]]]:
        """
        Execute a tool and yield (output, success, error).

        For the Task tool, yields StreamEvents from the subagent.
        """
        try:
            workspace = Path(self.config.cwd)

            if tool_name == "bash":
                command = args.get("command", "")
                timeout = args.get("timeout", 120)

                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR:\n{result.stderr}"
                if result.returncode != 0:
                    output += f"\nExit code: {result.returncode}"

                yield (output, True, None)

            elif tool_name == "read_file":
                path = args.get("path", "")
                offset = args.get("offset", 1)
                limit = args.get("limit")

                # Resolve path
                if path.startswith("/"):
                    full_path = Path(path)
                else:
                    full_path = workspace / path

                if not full_path.exists():
                    yield (f"File not found: {path}", False, "FileNotFound")
                    return

                lines = full_path.read_text().splitlines()

                # Apply offset and limit
                start = max(0, offset - 1)
                if limit:
                    lines = lines[start : start + limit]
                else:
                    lines = lines[start:]

                # Add line numbers
                numbered_lines = [
                    f"{i + offset:6d}\t{line}" for i, line in enumerate(lines)
                ]

                yield ("\n".join(numbered_lines), True, None)

            elif tool_name == "write_file":
                path = args.get("path", "")
                content = args.get("content", "")

                if path.startswith("/"):
                    full_path = Path(path)
                else:
                    full_path = workspace / path

                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

                yield (f"Wrote {len(content)} bytes to {path}", True, None)

            elif tool_name == "edit_file":
                path = args.get("path", "")
                old_string = args.get("old_string", "")
                new_string = args.get("new_string", "")

                if path.startswith("/"):
                    full_path = Path(path)
                else:
                    full_path = workspace / path

                if not full_path.exists():
                    yield (f"File not found: {path}", False, "FileNotFound")
                    return

                content = full_path.read_text()
                if old_string not in content:
                    yield (f"String not found in {path}", False, "StringNotFound")
                    return

                new_content = content.replace(old_string, new_string, 1)
                full_path.write_text(new_content)

                yield (f"Replaced text in {path}", True, None)

            elif tool_name == "glob":
                pattern = args.get("pattern", "*")
                base_path = args.get("path", ".")

                import glob as glob_module

                search_path = workspace / base_path / pattern
                matches = glob_module.glob(str(search_path), recursive=True)

                # Make paths relative
                rel_matches = []
                for m in matches[:200]:  # Limit results
                    try:
                        rel_matches.append(str(Path(m).relative_to(workspace)))
                    except ValueError:
                        rel_matches.append(m)

                yield ("\n".join(rel_matches) or "(no matches)", True, None)

            elif tool_name == "grep":
                pattern = args.get("pattern", "")
                path = args.get("path", ".")
                context = args.get("context", 0)

                cmd = ["grep", "-r", "-n"]
                if context > 0:
                    cmd.extend(["-C", str(context)])
                cmd.extend([pattern, path])

                result = subprocess.run(
                    cmd,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                output = result.stdout or "(no matches)"
                yield (output[:50000], True, None)  # Truncate large output

            elif tool_name == "task":
                subagent_name = args.get("subagent", "")
                prompt = args.get("prompt", "")

                if subagent_name not in self._subagent_executors:
                    yield (
                        f"Unknown subagent: {subagent_name}",
                        False,
                        "UnknownSubagent",
                    )
                    return

                executor = self._subagent_executors[subagent_name]

                # Stream subagent events
                subagent_output = []
                async for event in executor.execute(prompt, thread_id):
                    # For Task tool, we yield the events directly
                    # and collect output for the final result
                    if isinstance(event, StreamEvent):
                        if event.type == "thought":
                            subagent_output.append(event.data.get("text", ""))
                    yield ("__STREAM_EVENT__", event, None)

                # Return final summary
                yield ("\n".join(subagent_output[-3:]) or "Task completed", True, None)

            elif tool_name == "skill":
                skill_name = args.get("name", "")

                if not self._skills_loader:
                    yield ("Skills not available", False, "SkillsNotLoaded")
                    return

                skill = self._skills_loader.get_skill(skill_name)
                if not skill:
                    available = self._skills_loader.list_skills()
                    yield (
                        f"Skill '{skill_name}' not found. Available: {', '.join(available)}",
                        False,
                        "SkillNotFound",
                    )
                    return

                yield (skill["content"], True, None)

            elif tool_name == "web_search":
                query = args.get("query", "")
                num_results = min(args.get("num_results", 5), 10)

                # Use DuckDuckGo HTML search (no API key required)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    try:
                        response = await client.get(
                            "https://html.duckduckgo.com/html/",
                            params={"q": query},
                            headers={
                                "User-Agent": "Mozilla/5.0 (compatible; SREAgent/1.0)"
                            },
                        )
                        response.raise_for_status()

                        # Parse results from HTML
                        results = self._parse_duckduckgo_results(
                            response.text, num_results
                        )

                        if not results:
                            yield (f"No results found for: {query}", True, None)
                        else:
                            output_lines = [f"Search results for: {query}\n"]
                            for i, r in enumerate(results, 1):
                                output_lines.append(f"{i}. {r['title']}")
                                output_lines.append(f"   URL: {r['url']}")
                                output_lines.append(f"   {r['snippet']}\n")
                            yield ("\n".join(output_lines), True, None)

                    except httpx.HTTPError as e:
                        yield (f"Search failed: {str(e)}", False, "HTTPError")

            elif tool_name == "web_fetch":
                url = args.get("url", "")
                prompt = args.get("prompt", "")

                if not url:
                    yield ("URL is required", False, "MissingURL")
                    return

                async with httpx.AsyncClient(
                    timeout=30.0, follow_redirects=True
                ) as client:
                    try:
                        response = await client.get(
                            url,
                            headers={
                                "User-Agent": "Mozilla/5.0 (compatible; SREAgent/1.0)"
                            },
                        )
                        response.raise_for_status()

                        content_type = response.headers.get("content-type", "")

                        if "text/html" in content_type:
                            # Convert HTML to readable text
                            text = self._html_to_text(response.text)
                        else:
                            text = response.text

                        # Truncate if too long
                        if len(text) > 50000:
                            text = text[:50000] + "\n\n[Content truncated...]"

                        if prompt:
                            output = f"Content from {url}:\n\n{text}\n\n---\nExtraction request: {prompt}"
                        else:
                            output = f"Content from {url}:\n\n{text}"

                        yield (output, True, None)

                    except httpx.HTTPError as e:
                        yield (f"Fetch failed: {str(e)}", False, "HTTPError")

            else:
                yield (f"Unknown tool: {tool_name}", False, "UnknownTool")

        except subprocess.TimeoutExpired:
            yield ("Command timed out", False, "Timeout")
        except Exception as e:
            logger.error(f"[OpenHands] Tool error: {e}")
            yield (f"Error: {str(e)}", False, str(type(e).__name__))

    def _build_multimodal_content(
        self,
        text: str,
        images: Optional[list[dict]],
    ) -> list[dict]:
        """
        Build multimodal content for LiteLLM.

        Args:
            text: Text content
            images: Optional list of image dicts with {media_type, data}

        Returns:
            List of content parts for LiteLLM
        """
        content = [{"type": "text", "text": text}]

        if images:
            for img in images:
                media_type = img.get("media_type", "image/png")
                data = img.get("data", "")

                # Format for LiteLLM (OpenAI-compatible)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{data}",
                        },
                    }
                )

            logger.info(f"[OpenHands] Added {len(images)} image(s) to request")

        return content

    def _parse_duckduckgo_results(
        self, html_content: str, max_results: int
    ) -> list[dict]:
        """
        Parse search results from DuckDuckGo HTML.

        Args:
            html_content: Raw HTML from DuckDuckGo
            max_results: Maximum number of results to return

        Returns:
            List of dicts with title, url, snippet
        """
        results = []

        # Simple regex-based parsing for DuckDuckGo HTML results
        # Match result links and snippets
        result_pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>([^<]*)</a>',
            re.DOTALL | re.IGNORECASE,
        )

        for match in result_pattern.finditer(html_content):
            if len(results) >= max_results:
                break

            url = match.group(1)
            title = html.unescape(match.group(2).strip())
            snippet = html.unescape(match.group(3).strip())

            # DuckDuckGo uses redirect URLs, extract actual URL
            if "uddg=" in url:
                import urllib.parse

                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                url = parsed.get("uddg", [url])[0]

            if title and url:
                results.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet or "(no snippet)",
                    }
                )

        return results

    def _html_to_text(self, html_content: str) -> str:
        """
        Convert HTML to readable plain text.

        Args:
            html_content: Raw HTML

        Returns:
            Plain text with basic formatting preserved
        """
        # Remove script and style elements
        text = re.sub(
            r"<script[^>]*>.*?</script>",
            "",
            html_content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
        )

        # Convert common elements to text equivalents
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
        text = re.sub(r"<h[1-6][^>]*>", "\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)

        # Extract links
        text = re.sub(
            r'<a[^>]+href="([^"]*)"[^>]*>([^<]*)</a>',
            r"\2 (\1)",
            text,
            flags=re.IGNORECASE,
        )

        # Remove remaining tags
        text = re.sub(r"<[^>]+>", "", text)

        # Decode HTML entities
        text = html.unescape(text)

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = "\n".join(line.strip() for line in text.splitlines())

        return text.strip()

    @observe(name="openhands_execute")
    async def execute(
        self,
        prompt: str,
        images: Optional[list[dict]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Execute a query and stream events.

        Maintains conversation history across calls for multi-turn support.

        Args:
            prompt: User prompt
            images: Optional images for multimodal input

        Yields:
            StreamEvent objects
        """
        import json

        import litellm

        self.is_running = True
        self._was_interrupted = False
        final_text = ""

        try:
            # Initialize conversation history if empty (first turn)
            if not self._conversation_history:
                system_prompt = self._build_system_prompt()
                self._conversation_history = [
                    {"role": "system", "content": system_prompt},
                ]

            # Add user message (with images if provided)
            if images:
                user_content = self._build_multimodal_content(prompt, images)
                self._conversation_history.append(
                    {"role": "user", "content": user_content}
                )
            else:
                self._conversation_history.append({"role": "user", "content": prompt})

            # Use conversation history for this turn
            messages = self._conversation_history.copy()

            # Get tools schema
            tools = self._get_tools_schema()

            logger.info(f"[OpenHands] Starting execution with model: {self._model}")
            logger.info(
                f"[OpenHands] Tools available: {[t['function']['name'] for t in tools]}"
            )

            # Agent loop
            max_iterations = 50
            iteration = 0

            while iteration < max_iterations and self.is_running:
                iteration += 1

                try:
                    # Call LLM
                    response = await litellm.acompletion(
                        model=self._model,
                        messages=messages,
                        api_key=self._api_key,
                        tools=tools if tools else None,
                        tool_choice="auto" if tools else None,
                    )

                    assistant_message = response.choices[0].message
                    assistant_msg_dict = assistant_message.model_dump()

                    # Add to conversation history (persist across turns)
                    self._conversation_history.append(assistant_msg_dict)
                    messages.append(assistant_msg_dict)

                    # Check for tool calls
                    if assistant_message.tool_calls:
                        for tool_call in assistant_message.tool_calls:
                            tool_name = tool_call.function.name
                            tool_args_str = tool_call.function.arguments

                            # Parse arguments
                            try:
                                tool_args = (
                                    json.loads(tool_args_str) if tool_args_str else {}
                                )
                            except json.JSONDecodeError:
                                tool_args = {"raw": tool_args_str}

                            # Emit tool_start
                            yield tool_start_event(
                                self.thread_id,
                                tool_name,
                                tool_args,
                            )

                            # Execute tool
                            tool_output = ""
                            tool_success = True

                            async for result in self._execute_tool(
                                tool_name, tool_args, self.thread_id
                            ):
                                if result[0] == "__STREAM_EVENT__":
                                    # This is a streamed event from a subagent
                                    yield result[1]
                                else:
                                    output, success, error = result
                                    tool_output = output
                                    tool_success = success

                            # Emit tool_end
                            yield tool_end_event(
                                self.thread_id,
                                tool_name,
                                success=tool_success,
                                output=tool_output[:10000],  # Truncate
                            )

                            # Add tool result to messages and history
                            tool_result_msg = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": tool_output[:50000],  # Truncate for context
                            }
                            self._conversation_history.append(tool_result_msg)
                            messages.append(tool_result_msg)

                    else:
                        # No tool calls - we have a response
                        response_text = assistant_message.content or ""

                        if response_text:
                            yield thought_event(self.thread_id, response_text)
                            final_text = response_text

                        # Check if this is a final response or needs to continue
                        # LLMs typically stop when they have a complete answer
                        break

                except Exception as e:
                    logger.error(f"[OpenHands] LLM error: {e}")
                    import traceback

                    traceback.print_exc()

                    yield error_event(
                        self.thread_id,
                        f"LLM error: {str(e)}",
                        recoverable=False,
                    )
                    return

            if iteration >= max_iterations:
                logger.warning(f"[OpenHands] Reached max iterations ({max_iterations})")

            # Emit final result
            yield result_event(
                self.thread_id,
                final_text or "Task completed.",
                success=True,
                subtype="success",
            )

        except Exception as e:
            logger.error(f"[OpenHands] Execution error: {e}")
            import traceback

            traceback.print_exc()

            yield error_event(
                self.thread_id,
                str(e),
                recoverable=False,
            )

        finally:
            self.is_running = False

    async def interrupt(self) -> AsyncIterator[StreamEvent]:
        """Interrupt current execution."""
        self._was_interrupted = True
        self.is_running = False

        # Stop any running subagents
        for executor in self._subagent_executors.values():
            executor.stop()

        yield thought_event(self.thread_id, "Interrupting current task...")
        yield result_event(
            self.thread_id,
            "Task interrupted. Send a new message to continue.",
            success=True,
            subtype="interrupted",
        )

    async def close(self) -> None:
        """Clean up the provider."""
        self.is_running = False

        for executor in self._subagent_executors.values():
            executor.stop()

        self._subagent_executors.clear()
        self._conversation_history.clear()

    def set_answer_callback(self, callback: Callable[[dict], None]) -> None:
        """Set callback for receiving user answers (not fully implemented)."""
        pass

    async def provide_answer(self, answers: dict) -> None:
        """Provide answer to pending question (not fully implemented)."""
        if self._pending_answer_event is not None:
            self._pending_answer = answers
            self._pending_answer_event.set()
        else:
            logger.warning("[OpenHands] No pending question to answer")
