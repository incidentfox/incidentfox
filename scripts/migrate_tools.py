#!/usr/bin/env python3
"""
Migrate tool files from /agent to /unified-agent.

Handles two categories of tools:
1. ExecutionContext-based tools (most tools): Need significant adaptation
2. Direct function_tool tools: Only need import changes

Transformations applied:
- Replace imports (agents SDK → unified-agent core, ExecutionContext → os.getenv)
- Remove IntegrationNotConfiguredError → return JSON error dicts
- Add @function_tool decorator to functions missing it
- Wrap dict returns in json.dumps()
- Add register_tool() calls at the bottom
- Replace get_logger with logging.getLogger
"""

import os
import re
import sys
from pathlib import Path

# Paths
AGENT_TOOLS = Path("agent/src/ai_agent/tools")
UNIFIED_TOOLS = Path("unified-agent/src/unified_agent/tools")

# Tools already in unified-agent (skip these)
EXISTING_TOOLS = {
    "aws", "blameless", "coding", "datadog", "docker",
    "elasticsearch", "firehydrant", "git", "github", "gitlab",
    "grafana", "jira", "kubernetes", "meta", "pagerduty",
    "remediation", "sentry", "slack",
}

# Source file → target name mapping (strip _tools suffix)
def get_target_name(source_name: str) -> str:
    """Convert source filename to target filename."""
    name = source_name.replace("_tools", "")
    # Special cases
    if name == "thinking":
        return None  # Already in meta.py
    if name == "human_interaction":
        return None  # Handled differently in unified-agent
    if name == "tool_loader":
        return None  # Internal, not a tool module
    return name


def transform_imports(content: str) -> str:
    """Transform import statements."""
    # Track what we need
    has_json_import = "import json" in content
    has_logging_import = "import logging" in content
    has_os_import = "import os" in content

    lines = content.split("\n")
    new_lines = []
    added_unified_imports = False
    skip_next_blank = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Remove old agent-specific imports
        if any(stripped.startswith(p) for p in [
            "from agents import function_tool",
            "from ..core.config_required import",
            "from ..core.errors import",
            "from ..core.execution_context import",
            "from ..core.integration_errors import",
            "from ..core.logging import",
        ]):
            # Before removing, add unified-agent imports if not yet added
            if not added_unified_imports:
                if not has_json_import:
                    new_lines.append("import json")
                    has_json_import = True
                if not has_logging_import:
                    new_lines.append("import logging")
                    has_logging_import = True
                if not has_os_import:
                    new_lines.append("import os")
                    has_os_import = True
                new_lines.append("")
                new_lines.append("from ..core.agent import function_tool")
                new_lines.append("from . import register_tool")
                new_lines.append("")
                added_unified_imports = True
            # Skip the old import line
            continue

        # Fix get_logger
        if stripped == "logger = get_logger(__name__)":
            new_lines.append("logger = logging.getLogger(__name__)")
            continue

        new_lines.append(line)

    # If we never found old imports to replace, add unified imports after existing imports
    if not added_unified_imports:
        result_lines = []
        import_section_ended = False
        for line in new_lines:
            result_lines.append(line)
            if not import_section_ended and line.strip() == "" and any(
                l.strip().startswith(("import ", "from ")) for l in result_lines[-5:-1] if l.strip()
            ):
                if not has_json_import:
                    result_lines.append("import json")
                if not has_logging_import:
                    result_lines.append("import logging")
                if not has_os_import:
                    result_lines.append("import os")
                result_lines.append("")
                result_lines.append("from ..core.agent import function_tool")
                result_lines.append("from . import register_tool")
                result_lines.append("")
                import_section_ended = True
        new_lines = result_lines

    return "\n".join(new_lines)


def transform_config_function(content: str) -> str:
    """Transform _get_*_config() functions to use os.getenv only."""
    # Pattern: Remove the ExecutionContext block in config functions
    # This is the most complex transformation

    # Remove the context = get_execution_context() ... block
    # Pattern:
    #     context = get_execution_context()
    #     if context:
    #         config = context.get_integration_config("xxx")
    #         if config and config.get("yyy"):
    #             return ...
    #
    # We need to remove this entire block (typically 5-7 lines)

    lines = content.split("\n")
    new_lines = []
    skip_until_indent = None
    in_context_block = False
    context_block_indent = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect start of ExecutionContext block
        if "get_execution_context()" in stripped and not stripped.startswith("#"):
            # Find the indentation level
            context_block_indent = len(line) - len(line.lstrip())
            in_context_block = True
            # Add a comment instead
            indent = " " * context_block_indent
            new_lines.append(f"{indent}# Credentials from environment variables")
            i += 1
            continue

        # Skip lines in the context block
        if in_context_block:
            if stripped == "" or (len(line) - len(line.lstrip()) > context_block_indent):
                i += 1
                continue
            # Check if this is the "if context:" block or continuation
            if stripped.startswith("if context"):
                # Skip the entire if context block - find its end
                if_indent = len(line) - len(line.lstrip())
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    next_stripped = next_line.strip()
                    if next_stripped == "":
                        i += 1
                        continue
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent <= if_indent and next_stripped != "":
                        break
                    i += 1
                in_context_block = False
                continue
            else:
                in_context_block = False
                # Fall through to normal processing

        # Replace IntegrationNotConfiguredError raises with simple error return
        if "raise IntegrationNotConfiguredError" in stripped:
            indent = " " * (len(line) - len(line.lstrip()))
            # Find the closing paren
            paren_depth = stripped.count("(") - stripped.count(")")
            while paren_depth > 0 and i + 1 < len(lines):
                i += 1
                next_stripped = lines[i].strip()
                paren_depth += next_stripped.count("(") - next_stripped.count(")")

            # Extract integration name if possible
            match = re.search(r'integration_id="(\w+)"', content)
            integration_name = match.group(1) if match else "integration"
            new_lines.append(f'{indent}return {{"error": "{integration_name} not configured"}}')
            i += 1
            continue

        # Replace handle_integration_not_configured calls
        if "handle_integration_not_configured" in stripped:
            indent = " " * (len(line) - len(line.lstrip()))
            # Find the full call including closing paren
            full_call = stripped
            paren_depth = full_call.count("(") - full_call.count(")")
            while paren_depth > 0 and i + 1 < len(lines):
                i += 1
                next_stripped = lines[i].strip()
                full_call += " " + next_stripped
                paren_depth += next_stripped.count("(") - next_stripped.count(")")

            # Replace with error return
            match = re.search(r'integration_id="(\w+)"', full_call)
            integration_name = match.group(1) if match else "integration"
            new_lines.append(f'{indent}return json.dumps({{"ok": False, "error": "{integration_name} not configured"}})')
            i += 1
            continue

        # Replace ToolExecutionError raises
        if "raise ToolExecutionError" in stripped:
            indent = " " * (len(line) - len(line.lstrip()))
            # Extract the error message
            match = re.search(r'ToolExecutionError\("([^"]*)"', stripped)
            if match:
                msg = match.group(1)
            else:
                match = re.search(r'ToolExecutionError\((.+)\)', stripped)
                msg = match.group(1) if match else "Tool execution error"
            new_lines.append(f'{indent}return json.dumps({{"ok": False, "error": "{msg}"}})')
            i += 1
            continue

        new_lines.append(line)
        i += 1

    return "\n".join(new_lines)


def add_function_tool_decorators(content: str) -> str:
    """Add @function_tool decorators to public tool functions."""
    lines = content.split("\n")
    new_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check if this is a public function definition (not helper with _prefix)
        if stripped.startswith("def ") and not stripped.startswith("def _"):
            # Check if previous non-empty line is already @function_tool
            prev_non_empty = ""
            for j in range(i - 1, max(i - 5, -1), -1):
                if lines[j].strip():
                    prev_non_empty = lines[j].strip()
                    break

            if prev_non_empty != "@function_tool" and "@function_tool" not in prev_non_empty:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f"{indent}@function_tool")

        # Fix @function_tool(strict_mode=False) to @function_tool
        if stripped == "@function_tool(strict_mode=False)":
            indent = " " * (len(line) - len(line.lstrip()))
            new_lines.append(f"{indent}@function_tool")
            continue

        new_lines.append(line)

    return "\n".join(new_lines)


def fix_return_types(content: str) -> str:
    """
    Fix return type annotations from dict/list to str,
    and wrap dict returns in json.dumps() for functions with @function_tool.
    """
    # Fix return type annotations
    content = re.sub(
        r'(\) -> )dict\[.*?\](:)',
        r'\1str\2',
        content
    )
    content = re.sub(
        r'(\) -> )list\[.*?\](:)',
        r'\1str\2',
        content
    )
    content = re.sub(
        r'(\) -> )dict(:)',
        r'\1str\2',
        content
    )

    return content


def add_register_tool_calls(content: str, module_name: str) -> str:
    """Add register_tool() calls at the bottom of the file."""
    # Find all public function definitions (potential tools)
    functions = re.findall(r'^(?:@function_tool\n)?def (\w+)\(', content, re.MULTILINE)
    public_funcs = [f for f in functions if not f.startswith("_")]

    if not public_funcs:
        return content

    # Check if register_tool calls already exist
    if "register_tool(" in content:
        return content

    # Add registration section
    reg_lines = [
        "",
        "",
        "# Register tools",
    ]
    for func_name in public_funcs:
        reg_lines.append(f'register_tool("{func_name}", {func_name})')

    content = content.rstrip() + "\n" + "\n".join(reg_lines) + "\n"
    return content


def migrate_tool_file(source_path: Path, target_path: Path, module_name: str):
    """Migrate a single tool file."""
    print(f"  Migrating {source_path.name} → {target_path.name}")

    content = source_path.read_text()

    # Apply transformations in order
    content = transform_imports(content)
    content = transform_config_function(content)
    content = add_function_tool_decorators(content)
    content = fix_return_types(content)
    content = add_register_tool_calls(content, module_name)

    # Clean up multiple blank lines
    content = re.sub(r'\n{4,}', '\n\n\n', content)

    # Write output
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content)
    print(f"    ✓ Written {len(content)} bytes")


def update_init_py(new_modules: list[str]):
    """Update tools/__init__.py to register new tool modules."""
    init_path = UNIFIED_TOOLS / "__init__.py"
    content = init_path.read_text()

    # Find the insertion point (before the last section)
    # Add new imports in the _load_all_tools function
    new_imports = []
    for mod in sorted(new_modules):
        import_block = f"""
    try:
        from . import {mod}
    except ImportError:
        pass
"""
        if f"from . import {mod}" not in content:
            new_imports.append(import_block)

    if new_imports:
        # Insert before the last "try:" block (meta is currently last)
        # Find the position after the last existing import
        insertion_point = content.rfind("    try:\n        from . import meta")
        if insertion_point == -1:
            # Fallback: insert before the closing of _load_all_tools
            insertion_point = content.rfind("def get_proxy_headers")

        new_section = "\n    # Ported from /agent\n" + "".join(new_imports)
        content = content[:insertion_point] + new_section + "\n" + content[insertion_point:]

        init_path.write_text(content)
        print(f"  Updated __init__.py with {len(new_imports)} new module imports")


def main():
    """Run the migration."""
    os.chdir(Path(__file__).parent.parent)

    print("=" * 60)
    print("Tool Migration: /agent → /unified-agent")
    print("=" * 60)

    # Find all tool source files
    source_files = sorted(AGENT_TOOLS.glob("*_tools.py"))
    # Also include files without _tools suffix
    for f in sorted(AGENT_TOOLS.glob("*.py")):
        if f not in source_files and f.name != "__init__.py" and f.name != "tool_loader.py":
            source_files.append(f)

    migrated = []
    skipped = []

    for source in source_files:
        target_name = get_target_name(source.stem)
        if target_name is None:
            skipped.append(source.name)
            continue
        if target_name in EXISTING_TOOLS:
            skipped.append(f"{source.name} (already exists as {target_name}.py)")
            continue

        target_path = UNIFIED_TOOLS / f"{target_name}.py"
        if target_path.exists():
            skipped.append(f"{source.name} (target exists)")
            continue

        try:
            migrate_tool_file(source, target_path, target_name)
            migrated.append(target_name)
        except Exception as e:
            print(f"  ✗ FAILED: {source.name}: {e}")

    print(f"\n{'=' * 60}")
    print(f"Migrated: {len(migrated)} files")
    print(f"Skipped:  {len(skipped)} files")

    if skipped:
        print(f"\nSkipped files:")
        for s in skipped:
            print(f"  - {s}")

    if migrated:
        print(f"\nMigrated modules:")
        for m in migrated:
            print(f"  - {m}")

        # Update __init__.py
        print(f"\nUpdating __init__.py...")
        update_init_py(migrated)

    print(f"\n{'=' * 60}")
    print("IMPORTANT: Review migrated files for:")
    print("  1. Functions that return dict instead of json.dumps(str)")
    print("  2. ExecutionContext patterns not fully removed")
    print("  3. Missing @function_tool decorators on tool functions")
    print("  4. Incorrect register_tool() calls")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
