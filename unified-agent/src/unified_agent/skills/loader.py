"""
Skill Loader for Unified Agent.

Discovers and loads skills from filesystem with YAML frontmatter parsing.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A loaded skill definition."""

    name: str
    description: str
    content: str
    path: str
    category: str = ""
    required_integrations: List[str] = None

    def __post_init__(self):
        if self.required_integrations is None:
            self.required_integrations = []

    def __str__(self) -> str:
        return f"Skill({self.name})"


class SkillLoader:
    """
    Discovers and loads skills from the filesystem.

    Skills are markdown files with YAML frontmatter:
    ```
    ---
    name: skill-name
    description: When to use this skill
    ---

    # Skill Content
    ...
    ```
    """

    def __init__(self, skills_dirs: Optional[List[str]] = None):
        """
        Initialize skill loader.

        Args:
            skills_dirs: List of directories to search for skills.
                        Defaults to [cwd/.claude/skills, package_dir/skills]
        """
        self.skills_dirs = skills_dirs or self._get_default_dirs()
        self._cache: Dict[str, Skill] = {}

    def _get_default_dirs(self) -> List[str]:
        """Get default skill directories."""
        dirs = []

        # Project skills directory
        cwd = os.getenv("WORKSPACE_DIR", os.getcwd())
        project_skills = os.path.join(cwd, ".claude", "skills")
        if os.path.isdir(project_skills):
            dirs.append(project_skills)

        # Package bundled skills
        package_dir = Path(__file__).parent
        bundled_skills = package_dir / "bundled"
        if bundled_skills.is_dir():
            dirs.append(str(bundled_skills))

        return dirs

    def discover_skills(self) -> Dict[str, Skill]:
        """
        Discover all available skills.

        Returns:
            Dict of skill_name -> Skill
        """
        skills = {}

        for skills_dir in self.skills_dirs:
            if not os.path.isdir(skills_dir):
                continue

            # Find all SKILL.md files
            for root, dirs, files in os.walk(skills_dir):
                for filename in files:
                    if filename.upper() == "SKILL.MD":
                        skill_path = os.path.join(root, filename)
                        try:
                            skill = self._parse_skill_file(skill_path)
                            if skill:
                                skills[skill.name] = skill
                        except Exception as e:
                            logger.warning(
                                f"Failed to parse skill at {skill_path}: {e}"
                            )

        logger.debug(f"Discovered {len(skills)} skills")
        return skills

    def load_skill(self, skill_name: str) -> Optional[str]:
        """
        Load a specific skill's content.

        Args:
            skill_name: Name of the skill to load

        Returns:
            Skill content (markdown) or None if not found
        """
        # Check cache
        if skill_name in self._cache:
            return self._cache[skill_name].content

        # Discover if not cached
        skills = self.discover_skills()
        if skill_name in skills:
            self._cache[skill_name] = skills[skill_name]
            return skills[skill_name].content

        logger.warning(f"Skill not found: {skill_name}")
        return None

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """
        Get a skill object.

        Args:
            skill_name: Name of the skill

        Returns:
            Skill object or None
        """
        if skill_name in self._cache:
            return self._cache[skill_name]

        skills = self.discover_skills()
        if skill_name in skills:
            self._cache[skill_name] = skills[skill_name]
            return skills[skill_name]

        return None

    def list_skills(self) -> List[Dict]:
        """
        List all available skills with their metadata.

        Returns:
            List of skill metadata dicts
        """
        skills = self.discover_skills()
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "required_integrations": skill.required_integrations,
            }
            for skill in skills.values()
        ]

    def _parse_skill_file(self, path: str) -> Optional[Skill]:
        """
        Parse a SKILL.md file.

        Args:
            path: Path to SKILL.md file

        Returns:
            Skill object or None if invalid
        """
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse YAML frontmatter
        frontmatter_match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL
        )
        if not frontmatter_match:
            logger.warning(f"No frontmatter found in {path}")
            return None

        frontmatter_str = frontmatter_match.group(1)
        markdown_content = frontmatter_match.group(2)

        try:
            frontmatter = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            logger.warning(f"Invalid YAML frontmatter in {path}: {e}")
            return None

        name = frontmatter.get("name")
        description = frontmatter.get("description", "")
        category = frontmatter.get("category", "")
        required_integrations = frontmatter.get("required_integrations", [])

        if not name:
            # Use directory name as fallback
            name = os.path.basename(os.path.dirname(path))

        return Skill(
            name=name,
            description=description,
            content=markdown_content.strip(),
            path=path,
            category=category,
            required_integrations=required_integrations or [],
        )

    def get_skill_prompt_section(self, skill_name: str) -> str:
        """
        Get a skill formatted for injection into a prompt.

        Args:
            skill_name: Name of the skill

        Returns:
            Formatted skill section for prompt
        """
        skill = self.get_skill(skill_name)
        if not skill:
            return f"<!-- Skill '{skill_name}' not found -->"

        return f"""<skill name="{skill.name}">
{skill.content}
</skill>"""

    def format_skill_list(self) -> str:
        """
        Format skill list for display.

        Returns:
            Formatted string listing all skills
        """
        skills = self.list_skills()
        if not skills:
            return "No skills available."

        lines = ["Available skills:"]
        for skill in sorted(skills, key=lambda s: s["name"]):
            lines.append(f"  - {skill['name']}: {skill['description']}")

        return "\n".join(lines)
