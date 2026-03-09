# core/tui/skill_settings.py
"""
Skill Settings Management for TUI.

Provides helper functions for skill management commands in the TUI.
Similar to mcp_settings.py for MCP server management.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

from app.logger import logger

# Project root for skills directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"


def list_skills() -> List[Dict[str, Any]]:
    """
    List all discovered skills with their status.

    Returns:
        List of skill info dictionaries with name, description, enabled status, etc.
    """
    try:
        from app.skill import skill_manager

        skills = skill_manager.get_all_skills()
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "enabled": skill.enabled,
                "user_invocable": skill.metadata.user_invocable,
                "action_sets": skill.metadata.action_sets,
                "source": str(skill.source_path),
            }
            for skill in skills
        ]
    except ImportError:
        return []
    except Exception:
        return []


def get_skill_info(name: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a specific skill.

    Args:
        name: The skill name.

    Returns:
        Skill info dictionary or None if not found.
    """
    try:
        from app.skill import skill_manager

        skill = skill_manager.get_skill(name)
        if not skill:
            return None

        return {
            "name": skill.name,
            "description": skill.description,
            "enabled": skill.enabled,
            "user_invocable": skill.metadata.user_invocable,
            "argument_hint": skill.metadata.argument_hint,
            "action_sets": skill.metadata.action_sets,
            "allowed_tools": skill.metadata.allowed_tools,
            "source": str(skill.source_path),
            "instructions": skill.instructions,
        }
    except ImportError:
        return None
    except Exception:
        return None


def enable_skill(name: str) -> Tuple[bool, str]:
    """
    Enable a skill.

    Args:
        name: The skill name to enable.

    Returns:
        Tuple of (success, message).
    """
    try:
        from app.skill import skill_manager

        if skill_manager.enable_skill(name):
            return True, f"Skill '{name}' enabled."
        else:
            return False, f"Skill '{name}' not found."
    except ImportError:
        return False, "Skill system not available."
    except Exception as e:
        return False, f"Failed to enable skill: {e}"


def disable_skill(name: str) -> Tuple[bool, str]:
    """
    Disable a skill.

    Args:
        name: The skill name to disable.

    Returns:
        Tuple of (success, message).
    """
    try:
        from app.skill import skill_manager

        if skill_manager.disable_skill(name):
            return True, f"Skill '{name}' disabled."
        else:
            return False, f"Skill '{name}' not found."
    except ImportError:
        return False, "Skill system not available."
    except Exception as e:
        return False, f"Failed to disable skill: {e}"


def reload_skills() -> Tuple[bool, str]:
    """
    Reload skills from disk.

    Returns:
        Tuple of (success, message).
    """
    try:
        from app.skill import skill_manager

        count = skill_manager.reload_skills()
        return True, f"Reloaded {count} skills."
    except ImportError:
        return False, "Skill system not available."
    except Exception as e:
        return False, f"Failed to reload skills: {e}"


def get_skill_search_directories() -> List[str]:
    """
    Get the directories being searched for skills.

    Returns:
        List of absolute directory paths.
    """
    try:
        from app.skill import skill_manager

        status = skill_manager.get_status()
        dirs = status.get("search_dirs", [])
        # Convert to absolute paths
        return [str(Path(d).resolve()) for d in dirs]
    except ImportError:
        return []
    except Exception:
        return []


def toggle_skill(name: str) -> Tuple[bool, str]:
    """
    Toggle a skill's enabled state.

    Args:
        name: The skill name to toggle.

    Returns:
        Tuple of (success, message).
    """
    try:
        from app.skill import skill_manager

        skill = skill_manager.get_skill(name)
        if not skill:
            return False, f"Skill '{name}' not found."

        if skill.enabled:
            return disable_skill(name)
        else:
            return enable_skill(name)
    except ImportError:
        return False, "Skill system not available."
    except Exception as e:
        return False, f"Failed to toggle skill: {e}"


def get_skill_raw_content(name: str) -> Optional[str]:
    """
    Get the raw SKILL.md content for a skill.

    Args:
        name: The skill name.

    Returns:
        Raw markdown content or None if not found.
    """
    try:
        from app.skill import skill_manager

        skill = skill_manager.get_skill(name)
        if not skill:
            return None

        # Read the raw file content
        if skill.source_path.exists():
            return skill.source_path.read_text(encoding="utf-8")
        return None
    except ImportError:
        return None
    except Exception:
        return None


def _parse_skill_name_from_file(skill_md_path: Path) -> Optional[str]:
    """
    Parse skill name from SKILL.md frontmatter.

    Args:
        skill_md_path: Path to SKILL.md file.

    Returns:
        Skill name or None if not found.
    """
    try:
        content = skill_md_path.read_text(encoding="utf-8")
        # Match YAML frontmatter
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            # Find name field
            name_match = re.search(r"^name:\s*['\"]?([^'\"\n]+)['\"]?", frontmatter, re.MULTILINE)
            if name_match:
                return name_match.group(1).strip()
        # Fallback to directory name
        return skill_md_path.parent.name
    except Exception:
        return None


def install_skill_from_path(source_path: str) -> Tuple[bool, str]:
    """
    Install a skill from a local directory path.

    Args:
        source_path: Path to skill directory containing SKILL.md.

    Returns:
        Tuple of (success, message).
    """
    source = Path(source_path).resolve()

    # Validate source exists
    if not source.exists():
        return False, f"Path does not exist: {source_path}"

    # Check if it's a directory with SKILL.md
    if source.is_file() and source.name == "SKILL.md":
        source = source.parent
    elif source.is_dir():
        skill_md = source / "SKILL.md"
        if not skill_md.exists():
            return False, f"No SKILL.md found in: {source_path}"
    else:
        return False, f"Invalid path: {source_path}"

    # Get skill name from SKILL.md
    skill_md_path = source / "SKILL.md"
    skill_name = _parse_skill_name_from_file(skill_md_path)
    if not skill_name:
        skill_name = source.name

    # Validate skill name
    skill_name = skill_name.lower().replace(" ", "-")
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", skill_name):
        return False, f"Invalid skill name: {skill_name}. Use lowercase letters, numbers, and hyphens."

    # Ensure skills directory exists
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # Target directory
    target = SKILLS_DIR / skill_name

    # Check if already exists
    if target.exists():
        return False, f"Skill '{skill_name}' already exists at {target}"

    try:
        # Copy skill directory
        shutil.copytree(source, target)
        logger.info(f"Installed skill '{skill_name}' from {source}")

        # Reload skills
        reload_skills()

        return True, f"Installed skill '{skill_name}' to {target}"
    except Exception as e:
        return False, f"Failed to install skill: {e}"


def install_skill_from_git(url: str) -> Tuple[bool, str]:
    """
    Install a skill from a Git repository.

    Supports:
    - https://github.com/user/skill-repo
    - https://github.com/user/repo/tree/main/path/to/skill
    - git@github.com:user/skill-repo.git

    Args:
        url: Git repository URL.

    Returns:
        Tuple of (success, message).
    """
    # Parse URL to extract repo and optional subpath
    subpath = None
    clone_url = url

    # Handle GitHub tree URLs (https://github.com/user/repo/tree/branch/path)
    github_tree_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.*)",
        url
    )
    if github_tree_match:
        owner, repo, branch, subpath = github_tree_match.groups()
        clone_url = f"https://github.com/{owner}/{repo}.git"
        subpath = subpath.rstrip("/")

    # Handle GitLab tree URLs similarly
    gitlab_tree_match = re.match(
        r"https?://gitlab\.com/([^/]+)/([^/]+)/-/tree/([^/]+)/(.*)",
        url
    )
    if gitlab_tree_match:
        owner, repo, branch, subpath = gitlab_tree_match.groups()
        clone_url = f"https://gitlab.com/{owner}/{repo}.git"
        subpath = subpath.rstrip("/")

    # Create temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        clone_target = temp_path / "repo"

        try:
            # Clone repository (shallow clone for speed)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, str(clone_target)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return False, f"Git clone failed: {result.stderr}"

            # Navigate to subpath if specified
            skill_dir = clone_target
            if subpath:
                skill_dir = clone_target / subpath
                if not skill_dir.exists():
                    return False, f"Subpath not found in repository: {subpath}"

            # Find SKILL.md
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                # Try to find SKILL.md in subdirectories (single level)
                for child in skill_dir.iterdir():
                    if child.is_dir() and (child / "SKILL.md").exists():
                        skill_dir = child
                        skill_md = child / "SKILL.md"
                        break

            if not skill_md.exists():
                return False, f"No SKILL.md found in repository"

            # Install from the found path
            return install_skill_from_path(str(skill_dir))

        except subprocess.TimeoutExpired:
            return False, "Git clone timed out"
        except FileNotFoundError:
            return False, "Git is not installed or not in PATH"
        except Exception as e:
            return False, f"Failed to clone repository: {e}"


def get_skill_template(name: str, description: str = "") -> str:
    """
    Generate a standard SKILL.md template.

    Args:
        name: Skill name.
        description: Optional skill description.

    Returns:
        Template content as string.
    """
    skill_name = name.lower().replace(" ", "-").replace("_", "-")
    title = skill_name.replace("-", " ").title()
    desc = description or f"Custom skill for {title}"

    return f"""---
name: {skill_name}
description: {desc}
user-invocable: true
---

# {title}

{desc}

## When to Use

- Describe when this skill should be invoked
- List the scenarios where this skill is helpful
- Add more use cases as needed

## Instructions

Add your detailed instructions here. This content will be provided to the agent when the skill is invoked.

### Step 1: [First Step]

Describe what the agent should do first.

### Step 2: [Second Step]

Describe subsequent steps.

## Output Format

Describe how the agent should format its response when using this skill.

## Examples

Provide example interactions or outputs if helpful.
"""


def create_skill_scaffold(
    name: str, description: str = "", content: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Create a new skill with a template SKILL.md.

    Args:
        name: Skill name (will be converted to lowercase with hyphens).
        description: Optional skill description.
        content: Optional custom SKILL.md content. If not provided, uses template.

    Returns:
        Tuple of (success, message).
    """
    # Normalize name
    skill_name = name.lower().replace(" ", "-").replace("_", "-")

    # Validate name
    if not re.match(r"^[a-z][a-z0-9-]*$", skill_name):
        return False, f"Invalid skill name: {skill_name}. Use lowercase letters, numbers, and hyphens. Must start with a letter."

    # Ensure skills directory exists
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # Target directory
    target = SKILLS_DIR / skill_name

    if target.exists():
        return False, f"Skill '{skill_name}' already exists at {target}"

    try:
        # Create skill directory
        target.mkdir(parents=True)

        # Create SKILL.md with provided content or template
        skill_md = target / "SKILL.md"
        if content:
            skill_md.write_text(content, encoding="utf-8")
        else:
            skill_md.write_text(get_skill_template(skill_name, description), encoding="utf-8")

        logger.info(f"Created skill '{skill_name}' at {target}")

        # Reload skills
        reload_skills()

        return True, f"Created skill '{skill_name}' at {target}"
    except Exception as e:
        return False, f"Failed to create skill: {e}"


def remove_skill(name: str) -> Tuple[bool, str]:
    """
    Remove an installed skill from the skills directory.

    Only removes skills from the project skills/ folder, not user-level skills.

    Args:
        name: Skill name to remove.

    Returns:
        Tuple of (success, message).
    """
    skill_dir = SKILLS_DIR / name

    if not skill_dir.exists():
        # Try case-insensitive search
        for child in SKILLS_DIR.iterdir():
            if child.is_dir() and child.name.lower() == name.lower():
                skill_dir = child
                break

    if not skill_dir.exists():
        return False, f"Skill '{name}' not found in {SKILLS_DIR}"

    # Verify it's a skill directory (has SKILL.md)
    if not (skill_dir / "SKILL.md").exists():
        return False, f"'{name}' is not a valid skill directory (no SKILL.md)"

    try:
        shutil.rmtree(skill_dir)
        logger.info(f"Removed skill '{name}' from {skill_dir}")

        # Reload skills
        reload_skills()

        return True, f"Removed skill '{name}'"
    except Exception as e:
        return False, f"Failed to remove skill: {e}"
