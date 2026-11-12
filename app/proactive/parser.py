# -*- coding: utf-8 -*-
"""
Parser for the PROACTIVE.md file format.

PROACTIVE.md has three parts, two of them read by code:
- Cron Jobs: YAML job blocks between the CRON_JOBS markers.
- Heartbeat: a free-form checklist between the HEARTBEAT markers; the
  heartbeat reads it on every tick.
- Goals, Plan, and Status: maintained by the planners with file operations,
  never parsed or rewritten here.
"""

import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from .types import CronJob, ProactiveData


class ProactiveParser:
    """Parser for PROACTIVE.md.

    Sections are located by delimiter comments, so prose around them is
    free-form. Each cron job is a markdown header followed by a YAML block.
    """

    CRON_JOBS_START = "<!-- CRON_JOBS_START -->"
    CRON_JOBS_END = "<!-- CRON_JOBS_END -->"
    HEARTBEAT_START = "<!-- HEARTBEAT_START -->"
    HEARTBEAT_END = "<!-- HEARTBEAT_END -->"

    # Shown inside an empty Heartbeat section; comments never count as items.
    HEARTBEAT_PLACEHOLDER = (
        "<!-- Add what the heartbeat should check, one item per line, e.g.\n"
        "- Check my inbox for urgent email from clients -->"
    )

    # Regex patterns
    FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
    JOB_HEADER_PATTERN = re.compile(r"^###\s*\[(\w+)\]\s*(.+)$", re.MULTILINE)
    YAML_BLOCK_PATTERN = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
    HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)

    @classmethod
    def parse(cls, content: str) -> ProactiveData:
        """Parse PROACTIVE.md content into ProactiveData."""
        data = ProactiveData()

        frontmatter = cls._parse_frontmatter(content)
        data.version = frontmatter.get("version", "1.0")
        last_updated = frontmatter.get("last_updated")
        if isinstance(last_updated, str):
            try:
                data.last_updated = datetime.fromisoformat(
                    last_updated.replace("Z", "+00:00")
                )
            except ValueError:
                data.last_updated = None

        data.jobs = cls._parse_jobs(content)
        data.heartbeat_checklist = cls._parse_heartbeat(content)
        return data

    @classmethod
    def parse_file(cls, file_path: Path) -> ProactiveData:
        """Parse a PROACTIVE.md file."""
        return cls.parse(file_path.read_text(encoding="utf-8"))

    @classmethod
    def _section(cls, content: str, start: str, end: str) -> Optional[str]:
        """Text between two markers, or None when either is missing."""
        start_idx = content.find(start)
        end_idx = content.find(end)
        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            return None
        return content[start_idx + len(start) : end_idx]

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
    def _parse_jobs(cls, content: str) -> List[CronJob]:
        """Extract and parse the cron job blocks."""
        section = cls._section(content, cls.CRON_JOBS_START, cls.CRON_JOBS_END)
        if section is None:
            return []

        jobs = []
        header_matches = list(cls.JOB_HEADER_PATTERN.finditer(section))
        for i, header_match in enumerate(header_matches):
            frequency = header_match.group(1).lower()
            name = header_match.group(2).strip()

            start = header_match.end()
            end = (
                header_matches[i + 1].start()
                if i + 1 < len(header_matches)
                else len(section)
            )
            yaml_match = cls.YAML_BLOCK_PATTERN.search(section[start:end])
            if not yaml_match:
                continue
            try:
                yaml_data = yaml.safe_load(yaml_match.group(1))
            except yaml.YAMLError:
                continue
            if yaml_data:
                job = CronJob.from_dict(yaml_data, name=name)
                if not job.frequency:
                    job.frequency = frequency
                jobs.append(job)
        return jobs

    @classmethod
    def _parse_heartbeat(cls, content: str) -> str:
        """The Heartbeat checklist as written, minus marker comments."""
        section = cls._section(content, cls.HEARTBEAT_START, cls.HEARTBEAT_END)
        if section is None:
            return ""
        return cls.HTML_COMMENT_PATTERN.sub("", section).strip()

    @classmethod
    def serialize(cls, data: ProactiveData, template: Optional[str] = None) -> str:
        """Serialize ProactiveData back to PROACTIVE.md.

        With a template (the file as it is now), only the frontmatter, the
        Cron Jobs section and the Heartbeat section are regenerated; every
        other part of the file is kept exactly as it is.
        """
        if template:
            return cls._serialize_with_template(data, template)
        return cls._serialize_full(data)

    @classmethod
    def _replace_section(cls, text: str, start: str, end: str, body: str) -> str:
        start_idx = text.find(start)
        end_idx = text.find(end)
        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            return text
        return text[: start_idx + len(start)] + body + text[end_idx:]

    @classmethod
    def _heartbeat_body(cls, checklist: str) -> str:
        checklist = checklist.strip()
        return f"\n\n{checklist or cls.HEARTBEAT_PLACEHOLDER}\n\n"

    @classmethod
    def _serialize_with_template(cls, data: ProactiveData, template: str) -> str:
        result = template

        if cls.FRONTMATTER_PATTERN.match(result):
            stamp = (data.last_updated or datetime.now()).isoformat()
            new_frontmatter = (
                f"---\nversion: {data.version}\nlast_updated: {stamp}\n---"
            )
            result = cls.FRONTMATTER_PATTERN.sub(
                lambda _m: new_frontmatter, result, count=1
            )

        result = cls._replace_section(
            result,
            cls.CRON_JOBS_START,
            cls.CRON_JOBS_END,
            "\n\n" + cls._serialize_jobs(data.jobs) + "\n",
        )
        result = cls._replace_section(
            result,
            cls.HEARTBEAT_START,
            cls.HEARTBEAT_END,
            cls._heartbeat_body(data.heartbeat_checklist),
        )
        return result

    @classmethod
    def _serialize_full(cls, data: ProactiveData) -> str:
        """Serialize to a complete PROACTIVE.md (no file to keep)."""
        stamp = (data.last_updated or datetime.now()).isoformat()
        heartbeat = (
            cls.HEARTBEAT_START
            + cls._heartbeat_body(data.heartbeat_checklist)
            + cls.HEARTBEAT_END
        )
        return "\n".join(
            [
                "---",
                f"version: {data.version}",
                f"last_updated: {stamp}",
                "---",
                "",
                "# Proactive",
                "",
                cls._get_overview_text(),
                "",
                "## Cron Jobs",
                "",
                cls.CRON_JOBS_START,
                "",
                cls._serialize_jobs(data.jobs),
                cls.CRON_JOBS_END,
                "",
                "## Heartbeat",
                "",
                heartbeat,
                "",
                "## Goals, Plan, and Status",
                "",
                "### Long-Term Goals",
                "<!-- Updated by month planner -->",
                "No long-term goals defined yet.",
                "",
                "### Current Focus",
                "<!-- Updated by week/day planner -->",
                "No current focus defined.",
                "",
                "### Recent Accomplishments",
                "<!-- Updated by planners after task completion -->",
                "None yet.",
                "",
                "### Upcoming Priorities",
                "<!-- Updated by day planner -->",
                "None defined.",
            ]
        )

    @classmethod
    def _serialize_jobs(cls, jobs: List[CronJob]) -> str:
        """Serialize cron jobs to markdown with YAML blocks."""
        if not jobs:
            return "No cron jobs configured.\n"

        lines = []
        for freq in ("hourly", "daily", "weekly", "monthly"):
            for job in (j for j in jobs if j.frequency == freq):
                lines.append(f"### [{freq.upper()}] {job.name}")
                lines.append("```yaml")
                yaml_content = yaml.dump(
                    job.to_dict(),
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
                lines.append(yaml_content.rstrip())
                lines.append("```")
                lines.append("")
        return "\n".join(lines)

    @classmethod
    def _get_overview_text(cls) -> str:
        """The standard overview text for a freshly written PROACTIVE.md."""
        return """This file drives what you do without a user prompt.

- Cron Jobs: each job runs at its own set time (hourly at :MM, daily at HH:MM, weekly on a day, monthly on a date). When jobs are due, CraftBot starts a run in the main chat whose instruction lists exactly those jobs. A time missed while CraftBot was off runs once, late, when it is back.
- Heartbeat: every few minutes (Settings > Proactive), if the checklist below is not empty, you read it, check each item, act only if something needs attention, and report or end silently.
- Goals, Plan, and Status: kept up to date by the day, week and month planners.

CraftBot records each cron job run on the job entry; the run records its outcome."""


def validate_yaml_block(yaml_str: str) -> Tuple[bool, Optional[str]]:
    """Validate a YAML block for a cron job definition.

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            return False, "YAML must be a dictionary"

        required = ["id", "frequency", "instruction"]
        missing = [f for f in required if f not in data]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"

        valid_frequencies = ["hourly", "daily", "weekly", "monthly"]
        if data.get("frequency") not in valid_frequencies:
            return (
                False,
                f"Invalid frequency. Must be one of: {', '.join(valid_frequencies)}",
            )

        tier = data.get("permission_tier", 0)
        if not isinstance(tier, int) or tier < 0 or tier > 1:
            return False, "permission_tier must be 0 (silent) or 1 (notify)"

        return True, None

    except yaml.YAMLError as e:
        return False, f"Invalid YAML: {str(e)}"
