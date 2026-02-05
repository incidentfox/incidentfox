"""
Agent abstraction layer.

Provides an interface similar to OpenAI's Agents SDK but backed by
OpenHands/LiteLLM for multi-model support (Claude, Gemini, OpenAI).

This allows the config-driven agent builder from agent/ to work
with the sandbox infrastructure from sre-agent/.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ModelSettings:
    """Model configuration settings."""

    temperature: float = 0.4
    max_tokens: Optional[int] = None
    # For reasoning models (o1, o3, etc.)
    reasoning: Optional[dict] = None
    verbosity: Optional[str] = None


@dataclass
class AgentDefinition:
    """
    Definition of an agent for use in config-driven creation.

    This mirrors the AgentDefinition from Claude SDK but works with
    any LiteLLM-supported model.
    """

    description: str
    prompt: str
    tools: list[str] = field(default_factory=list)
    model: str = "sonnet"  # Alias that gets mapped to full model name


@dataclass
class Agent:
    """
    An agent that can be run with the Runner.

    This provides the same interface as OpenAI's Agent class but
    uses OpenHands/LiteLLM under the hood.

    Example:
        agent = Agent(
            name="Incident Investigator",
            instructions="You are an SRE expert...",
            model="anthropic/claude-sonnet-4-20250514",
            tools=[list_pods, describe_pod, get_pod_logs],
        )

        result = await Runner.run(agent, "Why is the checkout service slow?")
    """

    name: str
    instructions: str
    model: str
    tools: list[Callable] = field(default_factory=list)
    model_settings: Optional[ModelSettings] = None
    output_type: Optional[type] = None
    # Sub-agents that this agent can delegate to
    sub_agents: dict[str, "Agent"] = field(default_factory=dict)

    def __post_init__(self):
        if self.model_settings is None:
            self.model_settings = ModelSettings()

    def get_tool_by_name(self, name: str) -> Optional[Callable]:
        """Get a tool by its function name."""
        for tool in self.tools:
            tool_name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
            if tool_name == name:
                return tool
        return None

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """
        Get OpenAI-compatible tools schema for all tools.

        Returns list of tool definitions in the format expected by LiteLLM.
        """
        schemas = []
        for tool in self.tools:
            schema = _tool_to_schema(tool)
            if schema:
                schemas.append(schema)
        return schemas


def _tool_to_schema(tool: Callable) -> Optional[dict[str, Any]]:
    """
    Convert a tool function to OpenAI-compatible schema.

    Supports:
    - Functions decorated with @function_tool
    - Plain functions with type hints
    - Tool objects with .schema property
    """
    # Check if tool has pre-defined schema
    if hasattr(tool, "schema"):
        return tool.schema

    # Check for function_tool decorator metadata
    if hasattr(tool, "_tool_schema"):
        return tool._tool_schema

    # Build schema from function signature
    import inspect
    from typing import get_type_hints

    try:
        sig = inspect.signature(tool)
        hints = get_type_hints(tool) if hasattr(tool, "__annotations__") else {}
        doc = inspect.getdoc(tool) or ""

        # Extract first line as description
        description = doc.split("\n")[0] if doc else f"Call {tool.__name__}"

        # Build parameters schema
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = hints.get(param_name, str)
            param_schema = _type_to_json_schema(param_type)

            # Extract param description from docstring
            param_schema["description"] = _extract_param_doc(doc, param_name)

            properties[param_name] = param_schema

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": tool.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
    except Exception:
        # Fallback for tools that can't be introspected
        return {
            "type": "function",
            "function": {
                "name": getattr(tool, "__name__", "unknown_tool"),
                "description": getattr(tool, "__doc__", "") or "Execute tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }


def _type_to_json_schema(python_type: type) -> dict[str, Any]:
    """Convert Python type to JSON schema type."""
    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }

    # Handle Optional types
    origin = getattr(python_type, "__origin__", None)
    if origin is type(None):
        return {"type": "null"}

    # Handle Union (Optional is Union[X, None])
    if origin is type(None) or str(origin) == "typing.Union":
        args = getattr(python_type, "__args__", ())
        for arg in args:
            if arg is not type(None):
                return _type_to_json_schema(arg)

    return type_map.get(python_type, {"type": "string"})


def _extract_param_doc(docstring: str, param_name: str) -> str:
    """Extract parameter description from docstring."""
    if not docstring:
        return f"The {param_name} parameter"

    # Look for Args: section
    lines = docstring.split("\n")
    in_args = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            if stripped.startswith(param_name + ":"):
                return stripped.split(":", 1)[1].strip()
            if stripped and not stripped.startswith(" ") and ":" not in stripped:
                in_args = False

    return f"The {param_name} parameter"


def function_tool(func: Callable) -> Callable:
    """
    Decorator to mark a function as a tool.

    This provides compatibility with the @function_tool pattern from
    both OpenAI SDK and our custom tools.

    Example:
        @function_tool
        def list_pods(namespace: str = "default") -> str:
            '''List all pods in a namespace.'''
            ...
    """
    # Pre-compute schema for efficiency
    func._tool_schema = _tool_to_schema(func)
    func._is_tool = True
    return func
