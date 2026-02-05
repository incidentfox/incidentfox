"""
Skills System for Unified Agent.

Skills are markdown files with YAML frontmatter that provide domain-specific
knowledge and methodologies. They enable progressive disclosure - the agent
loads relevant skills based on the investigation context.

Structure of a skill (SKILL.md):
```yaml
---
name: skill-name
description: When to use this skill
---

# Skill Instructions

Markdown content with methodology, scripts, and examples.
```

Usage:
```python
from unified_agent.skills import SkillLoader

loader = SkillLoader()
skills = loader.discover_skills()
content = loader.load_skill("investigate")
```
"""

from .loader import Skill, SkillLoader

__all__ = ["SkillLoader", "Skill"]
