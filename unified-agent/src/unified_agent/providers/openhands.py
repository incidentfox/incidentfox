"""
OpenHands Provider for Unified Agent.

This module implements the LLMProvider interface using LiteLLM,
enabling multi-LLM support (Claude, Gemini, OpenAI, etc.) with full
feature parity.

Features:
- Multi-LLM support via LiteLLM (Claude, Gemini, OpenAI)
- Skills system: Auto-discovers and loads skills from .claude/skills/
- Subagents: Isolated context execution
- Image support: Multimodal input for supported models
- Tool output capture: Streams tool results back to caller
- Conversation history persistence across turns
"""

import asyncio
import glob as glob_module
import html
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

import httpx
import litellm
import yaml

from ..core.events import (
    StreamEvent,
    error_event,
    result_event,
    thought_event,
    tool_end_event,
    tool_start_event,
)
from .base import LLMProvider, ProviderConfig, SubagentConfig

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
        """Parse a skill markdown file with YAML frontmatter."""
        content = skill_file.read_text()

        # Parse YAML frontmatter (between --- markers)
        frontmatter_match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL
        )

        if not frontmatter_match:
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
        """Get a summary of all available skills for the system prompt."""
        if not self._skills_cache:
            return "No skills available."

        lines = ["## Available Skills\n"]
        lines.append("Use the appropriate skill for domain-specific tasks:\n")

        for name, skill in sorted(self._skills_cache.items()):
            lines.append(f"- **{name}**: {skill['description']}")

        lines.append("\nTo use a skill, call the 'skill' tool with the skill name.")
        return "\n".join(lines)

    def get_skill(self, name: str) -> Optional[dict]:
        """Get a specific skill by name."""
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
        """Execute a task in the subagent's isolated context."""
        self._is_running = True

        try:
            system_prompt = self._build_system_prompt()

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_prompt},
            ]

            yield thought_event(
                thread_id,
                f"[Subagent:{self.config.name}] Starting task...",
            )

            max_iterations = 20
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

                    if assistant_message.tool_calls:
                        for tool_call in assistant_message.tool_calls:
                            tool_name = tool_call.function.name
                            tool_args = tool_call.function.arguments

                            try:
                                args = json.loads(tool_args) if tool_args else {}
                            except json.JSONDecodeError:
                                args = {"raw": tool_args}

                            yield tool_start_event(thread_id, tool_name, args)

                            tool_result = await self._execute_tool(tool_name, args)

                            yield tool_end_event(
                                thread_id,
                                tool_name,
                                success=not tool_result.get("error"),
                                output=tool_result.get("output", "")[:5000],
                            )

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": tool_result.get("output", ""),
                                }
                            )
                    else:
                        final_response = assistant_message.content or ""
                        if final_response:
                            yield thought_event(thread_id, final_response)
                        break

                except Exception as e:
                    logger.error(f"[Subagent:{self.config.name}] Error: {e}")
                    yield error_event(
                        thread_id, f"Subagent error: {str(e)}", recoverable=True
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
                                    "description": "Path to the file",
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
                                    "description": "Search pattern",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "File or directory to search",
                                },
                            },
                            "required": ["pattern"],
                        },
                    },
                }
            )

        return tools

    async def _execute_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return result."""
        workspace = Path(self.workspace_dir)

        try:
            if tool_name == "bash":
                command = args.get("command", "")
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR:\n{result.stderr}"
                return {"output": output}

            elif tool_name == "read_file":
                path = args.get("path", "")
                full_path = Path(path) if path.startswith("/") else workspace / path
                if not full_path.exists():
                    return {"output": f"File not found: {path}", "error": True}
                return {"output": full_path.read_text()}

            elif tool_name == "glob":
                pattern = args.get("pattern", "")
                matches = list(
                    glob_module.glob(str(workspace / pattern), recursive=True)
                )
                return {"output": "\n".join(matches[:100])}

            elif tool_name == "grep":
                pattern = args.get("pattern", "")
                path = args.get("path", ".")
                full_path = workspace / path
                result = subprocess.run(
                    ["grep", "-rn", pattern, str(full_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return {"output": result.stdout or "No matches found"}

            else:
                return {"output": f"Unknown tool: {tool_name}", "error": True}

        except Exception as e:
            return {"output": f"Error: {str(e)}", "error": True}

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

        self._model = config.model or os.getenv(
            "LLM_MODEL", "anthropic/claude-sonnet-4-20250514"
        )
        self._api_key = self._get_api_key()

        self._skills_loader: Optional[SkillLoader] = None
        self._subagent_executors: dict[str, SubagentExecutor] = {}
        self._conversation_history: list[dict] = []
        self._is_running = False

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
        skills_dir = self.config.skills_dir or f"{self.config.cwd}/.claude/skills"
        if Path(skills_dir).exists():
            self._skills_loader = SkillLoader(skills_dir)
        else:
            logger.warning(f"[OpenHands] Skills directory not found: {skills_dir}")

        # Initialize subagent executors
        for name, subagent_config in self.config.subagents.items():
            subagent_model = self._map_subagent_model(subagent_config.model)

            self._subagent_executors[name] = SubagentExecutor(
                config=subagent_config,
                model=subagent_model,
                api_key=self._api_key,
                workspace_dir=self.config.cwd,
                skills_loader=self._skills_loader,
            )

        logger.info(f"[OpenHands] Provider initialized with model: {self._model}")
        if self._skills_loader:
            logger.info(
                f"[OpenHands] Skills loaded: {self._skills_loader.list_skills()}"
            )
        logger.info(f"[OpenHands] Subagents: {list(self._subagent_executors.keys())}")

    def _map_subagent_model(self, model_name: str) -> str:
        """Map model aliases to LiteLLM format."""
        model_mapping = {
            "sonnet": self._model,
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
        # Use custom system prompt from team config if available
        if self.config.system_prompt:
            parts = [self.config.system_prompt]
        else:
            parts = [
                "You are an AI agent for incident investigation and infrastructure automation.",
                "",
                "## Core Principles",
                "- Always investigate before acting",
                "- Use dry-run mode for dangerous operations",
                "- Report findings clearly and concisely",
                "- Use subagents for isolated deep-dive analysis",
                "",
            ]

        if self._skills_loader:
            parts.append(self._skills_loader.get_skill_summaries())
            parts.append("")

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
        allowed = self.config.allowed_tools

        if "Bash" in allowed:
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

        if "Read" in allowed:
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

        if "Write" in allowed:
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

        if "Edit" in allowed:
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

        if "Glob" in allowed:
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
                                    "description": "Glob pattern (e.g., '**/*.py')",
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

        if "Grep" in allowed:
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

        if "Task" in allowed and self._subagent_executors:
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
                                    "description": "Subagent to use",
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

        if "Skill" in allowed and self._skills_loader:
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
                                        "description": "Skill to load",
                                    },
                                },
                                "required": ["name"],
                            },
                        },
                    }
                )

        if "WebSearch" in allowed:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web for information",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query",
                                },
                                "num_results": {
                                    "type": "integer",
                                    "description": "Number of results (default: 5)",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            )

        if "WebFetch" in allowed:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "description": "Fetch content from a URL",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "URL to fetch",
                                },
                            },
                            "required": ["url"],
                        },
                    },
                }
            )

        # Add all registered tools (pagerduty, kubernetes, github, etc.)
        tools.extend(self._get_registry_tools_schema())

        return tools

    # Built-in tool names that have custom execution logic in _execute_tool.
    # Registry tools with these names are skipped to avoid duplicates.
    _BUILTIN_TOOL_NAMES = frozenset(
        {
            "bash",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "task",
            "skill",
            "web_search",
            "web_fetch",
        }
    )

    def _get_registry_tools_schema(self) -> list[dict]:
        """Get OpenAI-compatible schemas for all registered tools."""
        from ..tools import get_tool_registry

        schemas = []
        for name, func in get_tool_registry().items():
            if name in self._BUILTIN_TOOL_NAMES:
                continue
            if hasattr(func, "_tool_schema") and func._tool_schema:
                schemas.append(func._tool_schema)
        return schemas

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
    ) -> AsyncIterator[tuple[str, bool, Optional[str]]]:
        """Execute a tool and yield (output, success, error)."""
        workspace = Path(self.config.cwd)

        try:
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

                full_path = Path(path) if path.startswith("/") else workspace / path

                if not full_path.exists():
                    yield (f"File not found: {path}", False, "FileNotFound")
                    return

                lines = full_path.read_text().splitlines()
                start = max(0, offset - 1)
                if limit:
                    lines = lines[start : start + limit]
                else:
                    lines = lines[start:]

                numbered_lines = [
                    f"{i + offset:6d}\t{line}" for i, line in enumerate(lines)
                ]
                yield ("\n".join(numbered_lines), True, None)

            elif tool_name == "write_file":
                path = args.get("path", "")
                content = args.get("content", "")

                full_path = Path(path) if path.startswith("/") else workspace / path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

                yield (f"Wrote {len(content)} bytes to {path}", True, None)

            elif tool_name == "edit_file":
                path = args.get("path", "")
                old_string = args.get("old_string", "")
                new_string = args.get("new_string", "")

                full_path = Path(path) if path.startswith("/") else workspace / path

                if not full_path.exists():
                    yield (f"File not found: {path}", False, "FileNotFound")
                    return

                content = full_path.read_text()
                if old_string not in content:
                    yield (
                        f"String not found in file: {old_string[:50]}...",
                        False,
                        "NotFound",
                    )
                    return

                new_content = content.replace(old_string, new_string, 1)
                full_path.write_text(new_content)

                yield (f"Edited {path}", True, None)

            elif tool_name == "glob":
                pattern = args.get("pattern", "")
                base_path = args.get("path", ".")

                search_path = workspace / base_path / pattern
                matches = list(glob_module.glob(str(search_path), recursive=True))
                matches = sorted(matches)[:200]

                yield (
                    "\n".join(matches) if matches else "No matches found",
                    True,
                    None,
                )

            elif tool_name == "grep":
                pattern = args.get("pattern", "")
                path = args.get("path", ".")
                context = args.get("context", 0)

                full_path = workspace / path

                cmd = ["grep", "-rn", pattern, str(full_path)]
                if context > 0:
                    cmd = ["grep", "-rn", f"-C{context}", pattern, str(full_path)]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                output = result.stdout or "No matches found"

                yield (output[:50000], True, None)

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
                subagent_output = []

                async for event in executor.execute(prompt, self.thread_id):
                    yield ("__STREAM_EVENT__", event, None)
                    if event.type == "thought":
                        subagent_output.append(event.data.get("text", ""))

                yield ("\n".join(subagent_output[-3:]) or "Task completed", True, None)

            elif tool_name == "skill":
                skill_name = args.get("name", "")

                if not self._skills_loader:
                    yield ("No skills available", False, "NoSkills")
                    return

                skill = self._skills_loader.get_skill(skill_name)
                if not skill:
                    yield (f"Skill not found: {skill_name}", False, "SkillNotFound")
                    return

                yield (skill["content"], True, None)

            elif tool_name == "web_search":
                query = args.get("query", "")
                num_results = args.get("num_results", 5)

                # Use DuckDuckGo HTML search
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            "https://html.duckduckgo.com/html/",
                            params={"q": query},
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=30,
                        )
                        # Parse results (simplified)
                        results = (
                            f"Search results for: {query}\n(Web search integration)"
                        )
                        yield (results, True, None)
                except Exception as e:
                    yield (f"Search error: {str(e)}", False, "SearchError")

            elif tool_name == "web_fetch":
                url = args.get("url", "")

                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            url, timeout=30, follow_redirects=True
                        )
                        content = response.text

                        # Convert HTML to text
                        text = self._html_to_text(content)
                        yield (text[:50000], True, None)
                except Exception as e:
                    yield (f"Fetch error: {str(e)}", False, "FetchError")

            else:
                # Try registry tools (pagerduty, kubernetes, github, etc.)
                from ..tools import get_tool

                tool_func = get_tool(tool_name)
                if tool_func:
                    if asyncio.iscoroutinefunction(tool_func):
                        result = await tool_func(**args)
                    else:
                        result = tool_func(**args)
                    yield (result, True, None)
                else:
                    yield (f"Unknown tool: {tool_name}", False, "UnknownTool")

        except subprocess.TimeoutExpired:
            yield ("Command timed out", False, "Timeout")
        except Exception as e:
            yield (f"Error: {str(e)}", False, str(type(e).__name__))

    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to readable text."""
        text = re.sub(
            r"<script[^>]*>.*?</script>",
            "",
            html_content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def execute(
        self,
        prompt: str,
        images: Optional[list[dict]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Execute a query and stream events."""
        self.is_running = True
        self._was_interrupted = False
        final_text = ""

        try:
            if not self._conversation_history:
                system_prompt = self._build_system_prompt()
                self._conversation_history = [
                    {"role": "system", "content": system_prompt}
                ]

            if images:
                user_content = self._build_multimodal_content(prompt, images)
                self._conversation_history.append(
                    {"role": "user", "content": user_content}
                )
            else:
                self._conversation_history.append({"role": "user", "content": prompt})

            messages = self._conversation_history.copy()
            tools = self._get_tools_schema()

            logger.info(f"[OpenHands] Starting execution with model: {self._model}")

            max_iterations = 50
            iteration = 0

            while iteration < max_iterations and self.is_running:
                iteration += 1

                try:
                    response = await litellm.acompletion(
                        model=self._model,
                        messages=messages,
                        api_key=self._api_key,
                        tools=tools if tools else None,
                        tool_choice="auto" if tools else None,
                    )

                    assistant_message = response.choices[0].message
                    assistant_msg_dict = assistant_message.model_dump()

                    self._conversation_history.append(assistant_msg_dict)
                    messages.append(assistant_msg_dict)

                    if assistant_message.tool_calls:
                        for tool_call in assistant_message.tool_calls:
                            tool_name = tool_call.function.name
                            tool_args_str = tool_call.function.arguments

                            try:
                                tool_args = (
                                    json.loads(tool_args_str) if tool_args_str else {}
                                )
                            except json.JSONDecodeError:
                                tool_args = {"raw": tool_args_str}

                            yield tool_start_event(self.thread_id, tool_name, tool_args)

                            tool_output = ""
                            tool_success = True

                            async for result in self._execute_tool(
                                tool_name, tool_args
                            ):
                                if result[0] == "__STREAM_EVENT__":
                                    yield result[1]
                                else:
                                    output, success, error = result
                                    tool_output = output
                                    tool_success = success

                            yield tool_end_event(
                                self.thread_id,
                                tool_name,
                                success=tool_success,
                                output=tool_output[:10000],
                            )

                            tool_result_msg = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": tool_output[:50000],
                            }
                            self._conversation_history.append(tool_result_msg)
                            messages.append(tool_result_msg)

                    else:
                        response_text = assistant_message.content or ""

                        if response_text:
                            yield thought_event(self.thread_id, response_text)
                            final_text = response_text

                        break

                except Exception as e:
                    logger.error(f"[OpenHands] LLM error: {e}")
                    yield error_event(
                        self.thread_id, f"LLM error: {str(e)}", recoverable=False
                    )
                    return

            if iteration >= max_iterations:
                logger.warning(f"[OpenHands] Reached max iterations ({max_iterations})")

            yield result_event(
                self.thread_id, final_text or "Task completed.", success=True
            )

        except Exception as e:
            logger.error(f"[OpenHands] Execution error: {e}")
            yield error_event(self.thread_id, str(e), recoverable=False)

        finally:
            self.is_running = False

    def _build_multimodal_content(self, text: str, images: list[dict]) -> list[dict]:
        """Build multimodal content for LiteLLM."""
        content = [{"type": "text", "text": text}]

        for img in images:
            media_type = img.get("media_type", "image/png")
            data = img.get("data", "")

            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                }
            )

        return content

    async def interrupt(self) -> AsyncIterator[StreamEvent]:
        """Interrupt current execution."""
        self._was_interrupted = True
        self.is_running = False

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
