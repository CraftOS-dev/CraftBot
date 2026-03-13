# -*- coding: utf-8 -*-
"""
Parser for PROACTIVE.md file format.

This module provides parsing and serialization for the structured PROACTIVE.md format
that uses YAML code blocks within markdown for machine-parseable task definitions.
"""

import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from .types import RecurringTask, RecurringData


class ProactiveParser:
    """Parser for PROACTIVE.md format.

    The format uses delimiter comments to safely identify sections:
    - <!-- PROACTIVE_TASKS_START --> ... <!-- PROACTIVE_TASKS_END -->

    The "Goals, Plan, and Status" section is maintained by planners via file operations
    and is not parsed programmatically.

    Each task is defined with a markdown header followed by a YAML code block.
    """

    TASKS_START = "<!-- PROACTIVE_TASKS_START -->"
    TASKS_END = "<!-- PROACTIVE_TASKS_END -->"

    # Regex patterns
    FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)
    TASK_HEADER_PATTERN = re.compile(r'^###\s*\[(\w+)\]\s*(.+)$', re.MULTILINE)
    YAML_BLOCK_PATTERN = re.compile(r'```yaml\s*\n(.*?)```', re.DOTALL)

    @classmethod
    def parse(cls, content: str) -> RecurringData:
        """Parse PROACTIVE.md content into RecurringData.

        Args:
            content: Raw content of PROACTIVE.md file

        Returns:
            RecurringData object with parsed tasks and metadata
        """
        data = RecurringData()

        # Parse frontmatter
        frontmatter = cls._parse_frontmatter(content)
        data.version = frontmatter.get("version", "1.0")
        last_updated = frontmatter.get("last_updated")
        if isinstance(last_updated, str):
            try:
                data.last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            except ValueError:
                data.last_updated = None

        # Parse tasks
        data.tasks = cls._parse_tasks(content)

        # Note: planner_outputs field is deprecated - planners now update
        # the "Goals, Plan, and Status" section via file operations

        return data

    @classmethod
    def parse_file(cls, file_path: Path) -> RecurringData:
        """Parse PROACTIVE.md file.

        Args:
            file_path: Path to PROACTIVE.md file

        Returns:
            RecurringData object with parsed tasks and metadata

        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        content = file_path.read_text(encoding="utf-8")
        return cls.parse(content)

    @classmethod
    def _parse_frontmatter(cls, content: str) -> Dict[str, Any]:
        """Extract and parse YAML frontmatter."""
        match = cls.FRONTMATTER_PATTERN.match(content)
        if match:
            try:
                return yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                return {}
        return {}

    @classmethod
    def _parse_tasks(cls, content: str) -> List[RecurringTask]:
        """Extract and parse task definitions from tasks section."""
        # Find tasks section
        start_idx = content.find(cls.TASKS_START)
        end_idx = content.find(cls.TASKS_END)
        if start_idx == -1 or end_idx == -1:
            return []

        tasks_content = content[start_idx + len(cls.TASKS_START):end_idx]

        # Find all task headers and their YAML blocks
        tasks = []
        header_matches = list(cls.TASK_HEADER_PATTERN.finditer(tasks_content))

        for i, header_match in enumerate(header_matches):
            frequency = header_match.group(1).lower()
            name = header_match.group(2).strip()

            # Find the YAML block after this header
            start = header_match.end()
            end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(tasks_content)
            section_content = tasks_content[start:end]

            yaml_match = cls.YAML_BLOCK_PATTERN.search(section_content)
            if yaml_match:
                try:
                    yaml_data = yaml.safe_load(yaml_match.group(1))
                    if yaml_data:
                        task = RecurringTask.from_dict(yaml_data, name=name)
                        # Ensure frequency matches header
                        if not task.frequency:
                            task.frequency = frequency
                        tasks.append(task)
                except yaml.YAMLError:
                    continue

        return tasks

    @classmethod
    def serialize(cls, data: RecurringData, template: Optional[str] = None) -> str:
        """Serialize RecurringData back to PROACTIVE.md format.

        Args:
            data: RecurringData to serialize
            template: Optional template to use (preserves non-task content)

        Returns:
            Formatted PROACTIVE.md content
        """
        if template:
            return cls._serialize_with_template(data, template)
        return cls._serialize_full(data)

    @classmethod
    def _serialize_with_template(cls, data: RecurringData, template: str) -> str:
        """Serialize using existing template, replacing only the tasks section."""
        result = template

        # Update frontmatter
        frontmatter_match = cls.FRONTMATTER_PATTERN.match(result)
        if frontmatter_match:
            new_frontmatter = f"""---
version: {data.version}
last_updated: {data.last_updated.isoformat() if data.last_updated else datetime.now().isoformat()}
---"""
            result = cls.FRONTMATTER_PATTERN.sub(new_frontmatter, result, count=1)

        # Update tasks section
        tasks_content = cls._serialize_tasks(data.tasks)
        start_idx = result.find(cls.TASKS_START)
        end_idx = result.find(cls.TASKS_END)
        if start_idx != -1 and end_idx != -1:
            result = (
                result[:start_idx + len(cls.TASKS_START)]
                + "\n\n"
                + tasks_content
                + "\n"
                + result[end_idx:]
            )

        # Note: "Goals, Plan, and Status" section is managed by planners via
        # file operations and is not modified by this serialization

        return result

    @classmethod
    def _serialize_full(cls, data: RecurringData) -> str:
        """Serialize to full PROACTIVE.md format."""
        lines = []

        # Frontmatter
        lines.append("---")
        lines.append(f"version: {data.version}")
        lines.append(f"last_updated: {data.last_updated.isoformat() if data.last_updated else datetime.now().isoformat()}")
        lines.append("---")
        lines.append("")

        # Header and overview
        lines.append("# Proactive Tasks")
        lines.append("")
        lines.append(cls._get_overview_text())
        lines.append("")

        # Tasks section
        lines.append(cls.TASKS_START)
        lines.append("")
        lines.append(cls._serialize_tasks(data.tasks))
        lines.append(cls.TASKS_END)
        lines.append("")

        # Goals, Plan, and Status section (placeholder - managed by planners)
        lines.append("## Goals, Plan, and Status")
        lines.append("")
        lines.append("### Long-Term Goals")
        lines.append("<!-- Updated by month planner -->")
        lines.append("No long-term goals defined yet.")
        lines.append("")
        lines.append("### Current Focus")
        lines.append("<!-- Updated by week/day planner -->")
        lines.append("No current focus defined.")
        lines.append("")
        lines.append("### Recent Accomplishments")
        lines.append("<!-- Updated by planners after task completion -->")
        lines.append("None yet.")
        lines.append("")
        lines.append("### Upcoming Priorities")
        lines.append("<!-- Updated by day planner -->")
        lines.append("None defined.")

        return "\n".join(lines)

    @classmethod
    def _serialize_tasks(cls, tasks: List[RecurringTask]) -> str:
        """Serialize tasks to markdown with YAML blocks."""
        if not tasks:
            return "No recurring tasks configured.\n"

        lines = []
        # Group tasks by frequency
        frequencies = ["hourly", "daily", "weekly", "monthly"]

        for freq in frequencies:
            freq_tasks = [t for t in tasks if t.frequency == freq]
            for task in freq_tasks:
                lines.append(f"### [{freq.upper()}] {task.name}")
                lines.append("```yaml")

                # Create YAML content
                yaml_data = task.to_dict()
                yaml_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
                lines.append(yaml_content.rstrip())

                lines.append("```")
                lines.append("")

        return "\n".join(lines)

    @classmethod
    def _get_overview_text(cls) -> str:
        """Get the standard overview text for PROACTIVE.md."""
        return """You can operate proactively based on scheduled activations. Schedules can be hourly (every X hours), daily (at a specific time), weekly (on a specific day), or monthly (on a specific date).

When a schedule fires, you execute a proactive check workflow. First, read PROACTIVE.md to understand configured proactive tasks and their conditions. Then research the agent file system for relevant context - user preferences, project status, organizational priorities.

Evaluate each potential proactive task using a five-dimension rubric. Score each dimension from 1 to 5:
- Impact: How significant is the outcome? (1=negligible, 5=critical)
- Risk: What could go wrong? (1=high risk, 5=no risk)
- Cost: Resources and effort required? (1=very high, 5=negligible)
- Urgency: How time-sensitive? (1=not urgent, 5=immediate)
- Confidence: Will the user accept this? (1=unlikely, 5=certain)

Add the scores. Tasks scoring 18 or above are strong candidates for execution. Tasks scoring 13-17 may be worth doing but might need user input first. Tasks below 13 should be skipped or deferred.

Before acting on any proactive task, follow the tiered permission model:
- Tier 0 (silent): Searching, analyzing, drafting, internal operations - proceed without notifying the user
- Tier 1 (notify): Inform user of task execution and findings - inform and proceed without waiting
- Tier 2 (approval): Actions that modify state or create artifacts - ask for approval before proceeding
- Tier 3 (high-risk): Emailing external parties, changing configs, sensitive operations - explicit detailed approval required

When requesting permission for proactive tasks, prefix your message with the star emoji to indicate it is a proactive request.

After executing proactive tasks, update PROACTIVE.md with what was done, when, and the outcome."""


def validate_yaml_block(yaml_str: str) -> Tuple[bool, Optional[str]]:
    """Validate a YAML block for task definition.

    Args:
        yaml_str: YAML content to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            return False, "YAML must be a dictionary"

        # Check required fields
        required = ["id", "frequency", "instruction"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"

        # Validate frequency
        valid_frequencies = ["hourly", "daily", "weekly", "monthly"]
        if data.get("frequency") not in valid_frequencies:
            return False, f"Invalid frequency. Must be one of: {', '.join(valid_frequencies)}"

        # Validate permission_tier
        tier = data.get("permission_tier", 0)
        if not isinstance(tier, int) or tier < 0 or tier > 3:
            return False, "permission_tier must be an integer from 0 to 3"

        return True, None

    except yaml.YAMLError as e:
        return False, f"Invalid YAML: {str(e)}"
