"""
Tests for new dict-based inheritance system.

Tests:
- Dict-based tools/sub_agents/mcps merging
- Simplified deep_merge without control keys
- Key-level inheritance
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.hierarchical_config import deep_merge


class TestDictBasedMerge:
    """Test new dict-based merge behavior."""

    def test_agent_tools_dict_merge(self):
        """Test that agent tools merge at key level."""
        # Org config
        org = {
            "agents": {
                "planner": {
                    "enabled": True,
                    "tools": {"think": True, "llm_call": True, "web_search": True},
                }
            }
        }

        # Team adds one tool
        team = {"agents": {"planner": {"tools": {"custom_tool": True}}}}

        # Merge
        result = deep_merge(org, team)

        # Should have all org tools + team tool
        assert result["agents"]["planner"]["tools"] == {
            "think": True,
            "llm_call": True,
            "web_search": True,
            "custom_tool": True,
        }

    def test_agent_tools_override(self):
        """Test that team can disable specific tools."""
        org = {
            "agents": {
                "planner": {
                    "tools": {"think": True, "llm_call": True, "web_search": True}
                }
            }
        }

        team = {
            "agents": {"planner": {"tools": {"web_search": False}}}  # Disable this one
        }

        result = deep_merge(org, team)

        # web_search should be disabled
        assert result["agents"]["planner"]["tools"] == {
            "think": True,
            "llm_call": True,
            "web_search": False,  # Overridden
        }

    def test_agent_sub_agents_dict_merge(self):
        """Test that sub_agents merge at key level."""
        org = {
            "agents": {"planner": {"sub_agents": {"investigation": True, "k8s": True}}}
        }

        team = {
            "agents": {"planner": {"sub_agents": {"aws": True}}}  # Add new sub-agent
        }

        result = deep_merge(org, team)

        # Should have all org sub-agents + team sub-agent
        assert result["agents"]["planner"]["sub_agents"] == {
            "investigation": True,
            "k8s": True,
            "aws": True,
        }

    def test_mcp_servers_dict_merge(self):
        """Test that MCP servers merge at key level."""
        org = {
            "mcp_servers": {
                "github-mcp": {
                    "enabled": True,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                }
            }
        }

        team = {
            "mcp_servers": {
                "team-custom-mcp": {
                    "enabled": True,
                    "command": "./custom-mcp",
                    "args": [],
                }
            }
        }

        result = deep_merge(org, team)

        # Should have both MCPs
        assert "github-mcp" in result["mcp_servers"]
        assert "team-custom-mcp" in result["mcp_servers"]
        assert result["mcp_servers"]["github-mcp"]["enabled"] is True
        assert result["mcp_servers"]["team-custom-mcp"]["enabled"] is True

    def test_mcp_override_enabled_flag(self):
        """Test that team can disable org's MCP."""
        org = {"mcp_servers": {"github-mcp": {"enabled": True, "command": "npx"}}}

        team = {"mcp_servers": {"github-mcp": {"enabled": False}}}  # Disable it

        result = deep_merge(org, team)

        # enabled flag should be overridden
        assert result["mcp_servers"]["github-mcp"]["enabled"] is False
        # But other fields inherited
        assert result["mcp_servers"]["github-mcp"]["command"] == "npx"

    def test_multi_level_inheritance(self):
        """Test org → sub-team → team hierarchy."""
        # Org level
        org = {"agents": {"planner": {"tools": {"think": True, "llm_call": True}}}}

        # Sub-team level adds one
        sub_team = {"agents": {"planner": {"tools": {"web_search": True}}}}

        # Team level adds another
        team = {"agents": {"planner": {"tools": {"custom_tool": True}}}}

        # Merge step by step
        result = deep_merge(org, sub_team)
        result = deep_merge(result, team)

        # Should have all tools from all levels
        assert result["agents"]["planner"]["tools"] == {
            "think": True,
            "llm_call": True,
            "web_search": True,
            "custom_tool": True,
        }

    def test_list_replacement(self):
        """Test that lists are replaced (not merged)."""
        base = {"some_list": ["a", "b", "c"]}

        override = {"some_list": ["d", "e"]}

        result = deep_merge(base, override)

        # Lists should replace entirely
        assert result["some_list"] == ["d", "e"]

    def test_primitive_replacement(self):
        """Test that primitives are replaced."""
        base = {"model": "gpt-5.2", "temperature": 0.7, "enabled": True}

        override = {"model": "claude-sonnet-4", "temperature": 0.3}

        result = deep_merge(base, override)

        # Overridden values
        assert result["model"] == "claude-sonnet-4"
        assert result["temperature"] == 0.3
        # Inherited value
        assert result["enabled"] is True

    def test_empty_dict_override(self):
        """Test that empty dict doesn't change inherited values (merge is additive)."""
        base = {"agents": {"planner": {"tools": {"think": True, "llm_call": True}}}}

        override = {
            "agents": {"planner": {"tools": {}}}  # Empty override - nothing to merge
        }

        result = deep_merge(base, override)

        # Empty dict doesn't clear - inherited values remain (this is correct behavior)
        assert result["agents"]["planner"]["tools"] == {"think": True, "llm_call": True}

    def test_deep_nesting(self):
        """Test deep nesting (5+ levels)."""
        base = {
            "level1": {"level2": {"level3": {"level4": {"level5": {"value": "base"}}}}}
        }

        override = {
            "level1": {
                "level2": {"level3": {"level4": {"level5": {"value": "override"}}}}
            }
        }

        result = deep_merge(base, override)

        # Should navigate deep and override
        assert (
            result["level1"]["level2"]["level3"]["level4"]["level5"]["value"]
            == "override"
        )


class TestNoControlKeys:
    """Test that control keys are not needed/supported."""

    def test_no_underscore_inherit(self):
        """Test that _inherit key doesn't have special meaning."""
        base = {"tools": {"think": True, "llm_call": True}}

        override = {
            "_inherit": False,  # Should be treated as regular key
            "tools": {"web_search": True},
        }

        result = deep_merge(base, override)

        # _inherit is just a regular key, doesn't affect merge
        assert result["_inherit"] is False
        assert result["tools"] == {"think": True, "llm_call": True, "web_search": True}

    def test_no_underscore_append(self):
        """Test that _append key doesn't have special meaning."""
        base = {"items": ["a", "b"]}

        override = {
            "_append": True,  # Should be treated as regular key
            "items": ["c", "d"],
        }

        result = deep_merge(base, override)

        # _append is just a regular key, lists still replace
        assert result["_append"] is True
        assert result["items"] == ["c", "d"]  # Replaced, not appended
