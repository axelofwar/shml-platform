"""
Agent Skills Loader - Loads skills from SKILL.md files following the Agent Skills standard.

Standard: https://agentskills.io/specification

Each skill is a directory containing:
- SKILL.md (required): YAML frontmatter + markdown instructions
- scripts/ (optional): Executable code
- references/ (optional): Additional documentation
- assets/ (optional): Templates, resources
"""

import os
import re
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Skills directory
SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class AgentSkill:
    """Represents a loaded Agent Skill following the standard."""

    # Required frontmatter
    name: str
    description: str

    # Optional frontmatter
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)

    # Content
    instructions: str = ""
    path: Path = field(default_factory=Path)

    # Derived
    activation_triggers: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Extract activation triggers from description."""
        # Parse key words from description for activation
        if not self.activation_triggers:
            desc_lower = self.description.lower()
            # Extract nouns and key phrases
            triggers = []

            # Common patterns
            patterns = [
                r"(?:when|use when|for)\s+(?:the\s+)?(?:user\s+)?(?:asks?|wants?|needs?)\s+(?:to\s+|about\s+)?([^,.]+)",
                r"(?:monitor|check|get|list|search|execute|run)\s+([^,.]+)",
            ]

            for pattern in patterns:
                matches = re.findall(pattern, desc_lower)
                triggers.extend(matches)

            # Also use words from name
            triggers.extend(self.name.replace("-", " ").split())

            # Clean and deduplicate
            self.activation_triggers = list(
                set(t.strip().lower() for t in triggers if len(t.strip()) > 2)
            )

    def is_activated(self, user_task: str) -> bool:
        """Check if this skill is relevant for the task."""
        task_lower = user_task.lower()

        # Check description keywords
        if any(trigger in task_lower for trigger in self.activation_triggers):
            return True

        # Check name
        if (
            self.name.replace("-", " ") in task_lower
            or self.name.replace("-", "") in task_lower
        ):
            return True

        return False

    def get_context(self) -> str:
        """Get the full skill instructions for the agent."""
        return self.instructions

    def get_scripts_path(self) -> Optional[Path]:
        """Get path to scripts directory if it exists."""
        scripts_path = self.path / "scripts"
        return scripts_path if scripts_path.exists() else None

    def get_references(self) -> List[Path]:
        """Get list of reference files."""
        refs_path = self.path / "references"
        if refs_path.exists():
            return list(refs_path.glob("*.md"))
        return []


def parse_skill_md(skill_path: Path) -> Optional[AgentSkill]:
    """Parse a SKILL.md file and return an AgentSkill object."""
    skill_md = skill_path / "SKILL.md"

    if not skill_md.exists():
        logger.warning(f"No SKILL.md found in {skill_path}")
        return None

    try:
        content = skill_md.read_text()

        # Parse YAML frontmatter
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)

        if not frontmatter_match:
            logger.error(f"No valid frontmatter in {skill_md}")
            return None

        frontmatter_text = frontmatter_match.group(1)
        instructions = content[frontmatter_match.end() :]

        # Parse YAML
        frontmatter = yaml.safe_load(frontmatter_text)

        # Validate required fields
        if "name" not in frontmatter:
            logger.error(f"Missing 'name' in {skill_md}")
            return None

        if "description" not in frontmatter:
            logger.error(f"Missing 'description' in {skill_md}")
            return None

        # Validate name matches directory
        if frontmatter["name"] != skill_path.name:
            logger.warning(
                f"Skill name '{frontmatter['name']}' doesn't match directory '{skill_path.name}'"
            )

        # Parse allowed-tools if present
        allowed_tools = []
        if "allowed-tools" in frontmatter:
            allowed_tools = frontmatter["allowed-tools"].split()

        return AgentSkill(
            name=frontmatter["name"],
            description=frontmatter["description"],
            license=frontmatter.get("license"),
            compatibility=frontmatter.get("compatibility"),
            metadata=frontmatter.get("metadata", {}),
            allowed_tools=allowed_tools,
            instructions=instructions,
            path=skill_path,
        )

    except yaml.YAMLError as e:
        logger.error(f"YAML error in {skill_md}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing {skill_md}: {e}")
        return None


def load_all_skills() -> Dict[str, AgentSkill]:
    """Load all skills from the skills directory."""
    skills = {}

    if not SKILLS_DIR.exists():
        logger.warning(f"Skills directory not found: {SKILLS_DIR}")
        return skills

    for skill_dir in SKILLS_DIR.iterdir():
        if skill_dir.is_dir() and not skill_dir.name.startswith("."):
            skill = parse_skill_md(skill_dir)
            if skill:
                skills[skill.name] = skill
                logger.info(f"Loaded skill: {skill.name}")

    logger.info(f"Loaded {len(skills)} skills from {SKILLS_DIR}")
    return skills


def get_skill_discovery_context(skills: Dict[str, AgentSkill]) -> str:
    """Generate discovery context (name + description) for all skills.

    This is loaded at startup to help the agent know what skills are available.
    ~100 tokens per skill as per Agent Skills spec.
    """
    lines = ["# Available Skills\n"]

    for name, skill in sorted(skills.items()):
        lines.append(f"## {name}")
        lines.append(f"{skill.description}\n")

    return "\n".join(lines)


def get_activated_skills_context(skills: Dict[str, AgentSkill], user_task: str) -> str:
    """Get full instructions for skills activated by the user task.

    This follows the progressive disclosure pattern:
    - Only load full instructions when the skill is activated
    """
    activated = []

    for name, skill in skills.items():
        if skill.is_activated(user_task):
            activated.append(skill)
            logger.info(f"Activated skill: {name} for task: {user_task[:50]}")

    if not activated:
        return ""

    sections = []
    for skill in activated:
        sections.append(f"# Skill: {skill.name}\n{skill.get_context()}")

    return "\n\n---\n\n".join(sections)


# Global skills registry
_skills_registry: Dict[str, AgentSkill] = {}


def get_skills_registry() -> Dict[str, AgentSkill]:
    """Get or initialize the skills registry."""
    global _skills_registry

    if not _skills_registry:
        _skills_registry = load_all_skills()

    return _skills_registry


def reload_skills() -> Dict[str, AgentSkill]:
    """Force reload all skills."""
    global _skills_registry
    _skills_registry = load_all_skills()
    return _skills_registry
