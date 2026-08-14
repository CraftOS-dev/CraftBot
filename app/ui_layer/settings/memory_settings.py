"""Memory settings management for UI layer.

Provides functions for managing memory mode and memory items
that can be used by any interface adapter (Browser, CLI).
"""

import json
import re
import shutil
from datetime import datetime
from typing import Dict, Any, Optional, List

from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    SETTINGS_CONFIG_PATH,
)
from agent_core.core.impl.memory.graph import (
    SUPERSEDED_MARKER,
    compute_item_id,
    normalize_timestamp,
    split_item_fields,
)
from agent_core.core.impl.memory.text_extract import is_indexable_file
from agent_core.core.impl.memory.tuning import (
    CANDIDATE_MAX_DEPTH,
    CANDIDATE_MAX_RESULTS,
    MEMORY_ITEM_WORD_LIMIT_DEFAULT,
    MEMORY_MAX_ITEMS_DEFAULT,
    MEMORY_PRUNE_TARGET_DEFAULT,
    PROCESSING_THRESHOLD_DEFAULT,
    PROCESSING_THRESHOLD_MAX,
    SCHEDULE_HOUR_DEFAULT,
    SCHEDULE_MINUTE_DEFAULT,
)


# Memory item regex pattern: [stamp] [category] content. The stamp slot
# accepts any bracketed token — stamp validity is metadata, never a gate on
# whether the item is listed. The canonical "YYYY-MM-DD HH:MM:SS" (validated
# by normalize_timestamp) is the only recognized timestamp format; other
# stamp content still lists the item, with the raw stamp as its identity.
# Content may carry structured tail fields ({entities: ...}, {superseded});
# those are parsed out by _parse_memory_items via the shared graph helpers.
MEMORY_ITEM_PATTERN = re.compile(
    r"^\[([^\]]+)\]\s+\[([\w\-]+)\]\s+(.+)$"
)

# Files that are always indexed (mirrors MemoryManager.INDEX_TARGET_FILES).
CORE_INDEX_FILES = [
    "AGENT.md",
    "PROACTIVE.md",
    "MEMORY.md",
    "USER.md",
    "EVENT_UNPROCESSED.md",
    "ENTITIES.md",
]

# Files never offered as index candidates: unbounded logs and transient
# scaffolding that would pollute retrieval.
_CANDIDATE_EXCLUDE = {
    "EVENT.md",
    "CONVERSATION_HISTORY.md",
    "TASK_HISTORY.md",
}

# Directories never descended into during the candidate scan: dependency
# trees and build output in the workspace can be enormous (and on Windows
# can exceed MAX_PATH, which makes blind recursion raise).
_CANDIDATE_SKIP_DIRS = {
    "node_modules",
    ".git",
    ".next",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
}

# Memory size and length thresholds are live-read from settings.json via the
# getter functions below, so values can be tuned without a code change.
# Defaults (tuning.py) kick in only when a key is missing from settings.json.

# ─────────────────────────────────────────────────────────────────────
# Memory Mode Control
# ─────────────────────────────────────────────────────────────────────


def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    if not SETTINGS_CONFIG_PATH.exists():
        return {
            "proactive": {"enabled": True},
            "memory": {"enabled": True},
            "general": {"agent_name": "CraftBot"},
        }

    try:
        with open(SETTINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "proactive": {"enabled": True},
            "memory": {"enabled": True},
            "general": {"agent_name": "CraftBot"},
        }


def _save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings to settings.json."""
    try:
        SETTINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False


def is_memory_enabled() -> bool:
    """Check if memory mode is enabled.

    Returns:
        True if memory mode is enabled, False otherwise.
    """
    settings = _load_settings()
    return settings.get("memory", {}).get("enabled", True)


def get_memory_max_items() -> int:
    """Upper bound on MEMORY.md item count before pruning kicks in."""
    return int(
        _load_settings().get("memory", {}).get("max_items", MEMORY_MAX_ITEMS_DEFAULT)
    )


def get_memory_processing_threshold_max() -> int:
    """Upper bound the threshold slider allows."""
    return PROCESSING_THRESHOLD_MAX


def get_memory_processing_threshold() -> int:
    """Unprocessed-event count that triggers processing on the fly (0 = off)."""
    raw = int(
        _load_settings()
        .get("memory", {})
        .get("processing_threshold", PROCESSING_THRESHOLD_DEFAULT)
    )
    return max(0, min(PROCESSING_THRESHOLD_MAX, raw))


def set_memory_processing_threshold(value: int) -> bool:
    """Persist the threshold-driven processing count (clamped to [0, max])."""
    settings = _load_settings()
    clamped = max(0, min(PROCESSING_THRESHOLD_MAX, int(value)))
    settings.setdefault("memory", {})["processing_threshold"] = clamped
    return _save_settings(settings)


def get_unprocessed_event_count() -> int:
    """Number of unprocessed event lines waiting in EVENT_UNPROCESSED.md.

    Event lines start with '[' (a bracketed timestamp); headers/blanks do not,
    matching how the memory-processing pre-check counts them.
    """
    path = AGENT_FILE_SYSTEM_PATH / "EVENT_UNPROCESSED.md"
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.strip().startswith("["))


def memory_needs_pruning() -> bool:
    """Whether MEMORY.md has reached the item cap and is due for pruning."""
    path = AGENT_FILE_SYSTEM_PATH / "MEMORY.md"
    if not path.exists():
        return False
    try:
        items = _parse_memory_items(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return len(items) >= get_memory_max_items()


def memory_scheduled_run_due() -> bool:
    """Whether the DAILY scheduled memory processing should proceed.

    Gated by the threshold: the daily run fires only when at least
    ``threshold`` unprocessed events have accumulated, so quiet days skip
    instead of processing nothing at the set time. Pruning (MEMORY.md over
    the item cap) is a separate reason to run. A threshold of 0 removes the
    minimum — the run proceeds whenever anything is pending.
    """
    threshold = get_memory_processing_threshold()
    count = get_unprocessed_event_count()
    if threshold <= 0:
        return count > 0 or memory_needs_pruning()
    return count >= threshold or memory_needs_pruning()


def _time_phrase(hour: int, minute: int) -> str:
    """12-hour clock phrase the schedule parser accepts ('3am', '3:30pm')."""
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}{suffix}" if not minute else f"{hour12}:{minute:02d}{suffix}"


def memory_schedule_expression(
    hour: int = SCHEDULE_HOUR_DEFAULT, minute: int = SCHEDULE_MINUTE_DEFAULT
) -> str:
    """Build the daily memory-processing schedule expression.

    Auto-processing is daily by design; only the time of day is configurable.
    """
    return f"every day at {_time_phrase(hour, minute)}"


def get_memory_prune_target() -> int:
    """Approximate number of oldest items the pruning phase should remove."""
    return int(
        _load_settings()
        .get("memory", {})
        .get("prune_target", MEMORY_PRUNE_TARGET_DEFAULT)
    )


def get_memory_item_word_limit() -> int:
    """Maximum words allowed per distilled memory item."""
    return int(
        _load_settings()
        .get("memory", {})
        .get("item_word_limit", MEMORY_ITEM_WORD_LIMIT_DEFAULT)
    )


def get_memory_mode() -> Dict[str, Any]:
    """Get the current memory mode status.

    Returns:
        Dict with 'success' and 'enabled' fields.
    """
    try:
        enabled = is_memory_enabled()
        return {"success": True, "enabled": enabled}
    except Exception as e:
        return {"success": False, "error": f"Failed to get memory mode: {str(e)}"}


def set_memory_mode(enabled: bool) -> Dict[str, Any]:
    """Set the memory mode on or off.

    When disabled:
    - Agent won't query memory for context
    - Agent won't log to EVENT_UNPROCESSED.md
    - Daily Memory Processing won't run

    Args:
        enabled: True to enable memory mode, False to disable.

    Returns:
        Dict with 'success' and optional 'error' fields.
    """
    try:
        settings = _load_settings()
        if "memory" not in settings:
            settings["memory"] = {}
        settings["memory"]["enabled"] = enabled

        if _save_settings(settings):
            return {"success": True, "enabled": enabled}
        else:
            return {"success": False, "error": "Failed to save settings"}
    except Exception as e:
        return {"success": False, "error": f"Failed to set memory mode: {str(e)}"}


# ─────────────────────────────────────────────────────────────────────
# Memory Items Management
# ─────────────────────────────────────────────────────────────────────


def _parse_memory_items(content: str) -> List[Dict[str, Any]]:
    """Parse memory items from MEMORY.md content.

    Item ids are the same deterministic (timestamp, content) hashes the
    MemoryManager uses for chunk ids, so the UI, the vector index, and the
    memory graph all reference an item by one identity. `content` in the
    returned dict keeps wikilinks (it round-trips through serialization);
    `display_content` has them stripped for rendering.
    """
    items = []
    seen_ids: Dict[str, int] = {}

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        match = MEMORY_ITEM_PATTERN.match(line)
        if not match:
            continue

        timestamp_str, category, item_content = match.groups()
        clean_content, entities, superseded = split_item_fields(item_content)

        # Hash the normalized timestamp — the MemoryManager chunker does the
        # same, so both derive the identical id for the same line.
        item_id = compute_item_id(
            normalize_timestamp(timestamp_str) or timestamp_str, clean_content
        )
        dup = seen_ids.get(item_id, 0)
        seen_ids[item_id] = dup + 1
        if dup:
            item_id = f"{item_id}-{dup + 1}"

        items.append(
            {
                "id": item_id,
                "timestamp": timestamp_str,
                "category": category.lower(),
                "content": clean_content,
                "display_content": clean_content,
                # Legacy {entities: ...} markup found on the line, exposed
                # for display only. Connections live in ENTITIES.md; the
                # serializer never writes this field back.
                "entities": entities or [],
                "entities_annotated": entities is not None,
                "superseded": superseded,
                "raw": line,
            }
        )

    return items


def _serialize_memory_items(items: List[Dict[str, Any]]) -> str:
    """Serialize memory items back to MEMORY.md format.

    Items are plain lines; the ONLY structured tail field is {superseded}.
    Legacy {entities: ...} markup is dropped on rewrite — connections are
    recorded in ENTITIES.md, never inline.
    """
    lines = []
    for item in items:
        fields = ""
        if item.get("superseded"):
            fields += f" {SUPERSEDED_MARKER}"
        line = f"[{item['timestamp']}] [{item['category']}] {item['content']}{fields}"
        lines.append(line)
    return "\n".join(lines)


def _read_memory_file() -> tuple[str, str]:
    """Read MEMORY.md and split into header and items sections.

    Returns:
        Tuple of (header_content, items_section)
    """
    memory_path = AGENT_FILE_SYSTEM_PATH / "MEMORY.md"

    if not memory_path.exists():
        return "", ""

    content = memory_path.read_text(encoding="utf-8")

    # Find the "## Memory" section
    memory_section_marker = "## Memory"
    if memory_section_marker in content:
        idx = content.index(memory_section_marker)
        header = content[: idx + len(memory_section_marker)]
        items_section = content[idx + len(memory_section_marker) :]
        return header, items_section.strip()

    return content, ""


def _write_memory_file(header: str, items_content: str) -> bool:
    """Write MEMORY.md with header and items.

    Args:
        header: The header/overview section
        items_content: The memory items content

    Returns:
        True if successful
    """
    memory_path = AGENT_FILE_SYSTEM_PATH / "MEMORY.md"

    try:
        full_content = header + "\n\n" + items_content + "\n"
        memory_path.write_text(full_content, encoding="utf-8")
        return True
    except Exception:
        return False


def get_memory_items() -> Dict[str, Any]:
    """Get all memory items from MEMORY.md.

    Returns:
        Dict with 'success', 'items' or 'error' fields
    """
    try:
        _, items_section = _read_memory_file()
        items = _parse_memory_items(items_section)

        # Group by category for convenience
        categories = {}
        for item in items:
            cat = item["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)

        return {
            "success": True,
            "items": items,
            "categories": list(categories.keys()),
            "count": len(items),
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to get memory items: {str(e)}"}


def add_memory_item(
    category: str, content: str, timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """Add a new memory item to MEMORY.md.

    Args:
        category: Memory category (e.g., 'preference', 'event', 'work')
        content: The memory content
        timestamp: Optional timestamp (defaults to now)

    Returns:
        Dict with 'success', 'item' or 'error' fields
    """
    try:
        if not timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        header, items_section = _read_memory_file()
        items = _parse_memory_items(items_section)

        # Create new item as a plain line ({superseded} is the only tail
        # field). Connections are established by the graph and recorded in
        # ENTITIES.md — never inline here.
        clean_content, _, superseded = split_item_fields(content)
        new_line = f"[{timestamp}] [{category.lower()}] {clean_content}" + (
            f" {SUPERSEDED_MARKER}" if superseded else ""
        )
        new_item = {
            "id": compute_item_id(
                normalize_timestamp(timestamp) or timestamp, clean_content
            ),
            "timestamp": timestamp,
            "category": category.lower(),
            "content": clean_content,
            "display_content": clean_content,
            "entities": [],
            "entities_annotated": False,
            "superseded": superseded,
            "raw": new_line,
        }

        items.append(new_item)

        # Write back
        items_content = _serialize_memory_items(items)
        if _write_memory_file(header, items_content):
            return {"success": True, "item": new_item}
        else:
            return {"success": False, "error": "Failed to write memory file"}
    except Exception as e:
        return {"success": False, "error": f"Failed to add memory item: {str(e)}"}


def update_memory_item(
    item_id: str,
    category: Optional[str] = None,
    content: Optional[str] = None,
    superseded: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update an existing memory item.

    Args:
        item_id: The item ID to update
        category: New category (optional)
        content: New content (optional)
        superseded: New superseded flag (optional). Marking an item
            superseded keeps it on file (history preserved) but removes
            it from retrieval.

    Returns:
        Dict with 'success', 'item' or 'error' fields
    """
    try:
        header, items_section = _read_memory_file()
        items = _parse_memory_items(items_section)

        # Find the item
        item_found = None
        for item in items:
            if item["id"] == item_id:
                item_found = item
                break

        if not item_found:
            return {"success": False, "error": f"Memory item not found: {item_id}"}

        # Update fields
        if category is not None:
            item_found["category"] = category.lower()
        if content is not None:
            # Structured tail markup in the edited text is stripped; items
            # are plain lines and connections live in ENTITIES.md.
            clean_content, _, _ = split_item_fields(content)
            item_found["content"] = clean_content
        if superseded is not None:
            item_found["superseded"] = superseded

        # Refresh derived fields
        item_found["display_content"] = item_found["content"]
        fields = ""
        if item_found.get("superseded"):
            fields += f" {SUPERSEDED_MARKER}"
        item_found["raw"] = (
            f"[{item_found['timestamp']}] [{item_found['category']}] "
            f"{item_found['content']}{fields}"
        )

        # Write back
        items_content = _serialize_memory_items(items)
        if _write_memory_file(header, items_content):
            return {"success": True, "item": item_found}
        else:
            return {"success": False, "error": "Failed to write memory file"}
    except Exception as e:
        return {"success": False, "error": f"Failed to update memory item: {str(e)}"}


def remove_memory_item(item_id: str) -> Dict[str, Any]:
    """Remove a memory item by ID.

    Args:
        item_id: The item ID to remove

    Returns:
        Dict with 'success' or 'error' fields
    """
    try:
        header, items_section = _read_memory_file()
        items = _parse_memory_items(items_section)

        # Find and remove the item
        original_count = len(items)
        items = [item for item in items if item["id"] != item_id]

        if len(items) == original_count:
            return {"success": False, "error": f"Memory item not found: {item_id}"}

        # Write back
        items_content = _serialize_memory_items(items)
        if _write_memory_file(header, items_content):
            return {"success": True}
        else:
            return {"success": False, "error": "Failed to write memory file"}
    except Exception as e:
        return {"success": False, "error": f"Failed to remove memory item: {str(e)}"}


def reset_memory() -> Dict[str, Any]:
    """Reset MEMORY.md by restoring from template.

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / "MEMORY.md"
    target_path = AGENT_FILE_SYSTEM_PATH / "MEMORY.md"

    try:
        if not template_path.exists():
            return {"success": False, "error": "MEMORY.md template not found"}

        # Copy template to target
        shutil.copy(template_path, target_path)

        # Read restored content
        content = target_path.read_text(encoding="utf-8")

        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": f"Failed to reset memory: {str(e)}"}


def clear_unprocessed_events() -> Dict[str, Any]:
    """Clear all unprocessed events from EVENT_UNPROCESSED.md.

    Returns:
        Dict with 'success' or 'error' fields
    """
    event_path = AGENT_FILE_SYSTEM_PATH / "EVENT_UNPROCESSED.md"
    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / "EVENT_UNPROCESSED.md"

    try:
        if template_path.exists():
            shutil.copy(template_path, event_path)
        else:
            # Write a minimal reset
            content = """# Unprocessed Event Log

Agent DO NOT append to this file, only delete processed event during memory processing.

## Overview

This file store all the unprocessed events run by the agent.
Once the agent run 'process memory' action, all the processed events will learned by the agent (move to MEMORY.md) and wiped from this file.

## Unprocessed Events

"""
            event_path.write_text(content, encoding="utf-8")

        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to clear unprocessed events: {str(e)}",
        }


def reset_entity_registry() -> Dict[str, Any]:
    """Reset ENTITIES.md (the entity registry) from template.

    Part of a full memory reset: without it the graph would keep the old
    file→entity links from the previous state. The entity-indexer rebuilds
    the registry for indexed files on its next run.
    """
    target_path = AGENT_FILE_SYSTEM_PATH / "ENTITIES.md"
    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / "ENTITIES.md"
    try:
        if template_path.exists():
            shutil.copy(template_path, target_path)
        else:
            target_path.write_text(
                "# Entity Registry\n\n## Entities\n\n## Connections\n",
                encoding="utf-8",
            )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"Failed to reset entity registry: {str(e)}"}


# ─────────────────────────────────────────────────────────────────────
# Indexed Files Management
# ─────────────────────────────────────────────────────────────────────


def get_memory_indexed_files() -> List[str]:
    """User-selected extra files to index, as relative paths.

    Core files (CORE_INDEX_FILES) are always indexed and are not part of
    this list. This function is handed to MemoryManager as its
    extra_files_provider, so panel changes apply on the next index pass.
    """
    files = _load_settings().get("memory", {}).get("indexed_files", [])
    if not isinstance(files, list):
        return []
    return [str(f) for f in files if isinstance(f, str) and f.strip()]


def set_memory_indexed_files(paths: List[str]) -> Dict[str, Any]:
    """Replace the extra indexed-files list.

    Paths are validated: relative, .md, inside the agent file system,
    existing, and not a core/excluded file. Invalid entries are reported
    back rather than silently dropped.
    """
    try:
        accepted: List[str] = []
        rejected: List[Dict[str, str]] = []
        seen = set(CORE_INDEX_FILES)

        for raw in paths or []:
            rel = str(raw).replace("\\", "/").strip().lstrip("/")
            if not rel or rel in seen:
                continue
            if not is_indexable_file(rel):
                rejected.append(
                    {"path": rel, "reason": "unsupported type (md, txt, pdf only)"}
                )
                continue
            if rel.split("/")[-1] in _CANDIDATE_EXCLUDE:
                rejected.append({"path": rel, "reason": "excluded system file"})
                continue
            try:
                resolved = (AGENT_FILE_SYSTEM_PATH / rel).resolve()
                resolved.relative_to(AGENT_FILE_SYSTEM_PATH.resolve())
            except (ValueError, OSError):
                rejected.append({"path": rel, "reason": "outside agent file system"})
                continue
            if not resolved.exists():
                rejected.append({"path": rel, "reason": "file not found"})
                continue
            seen.add(rel)
            accepted.append(rel)

        settings = _load_settings()
        if "memory" not in settings:
            settings["memory"] = {}
        settings["memory"]["indexed_files"] = accepted

        if not _save_settings(settings):
            return {"success": False, "error": "Failed to save settings"}
        return {"success": True, "files": accepted, "rejected": rejected}
    except Exception as e:
        return {"success": False, "error": f"Failed to set indexed files: {str(e)}"}


def list_indexable_candidates() -> Dict[str, Any]:
    """Markdown files under the agent file system that can be indexed.

    Scans the root and workspace up to a bounded depth, excluding core
    files (always indexed), oversized logs, and already-selected extras.
    """
    try:
        selected = set(get_memory_indexed_files())
        core = set(CORE_INDEX_FILES)
        root = AGENT_FILE_SYSTEM_PATH.resolve()

        # Explicit breadth-first walk with directory pruning. rglob would
        # descend into node_modules/build trees (huge, and on Windows their
        # deep paths can exceed MAX_PATH and raise mid-iteration).
        candidates: List[Dict[str, Any]] = []
        frontier: List[tuple] = [(root, 0)]
        while frontier and len(candidates) < CANDIDATE_MAX_RESULTS:
            directory, depth = frontier.pop(0)
            try:
                entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        if (
                            depth + 1 < CANDIDATE_MAX_DEPTH
                            and entry.name not in _CANDIDATE_SKIP_DIRS
                            and not entry.name.startswith(".")
                        ):
                            frontier.append((entry, depth + 1))
                        continue
                    if not is_indexable_file(entry.name):
                        continue
                    rel = str(entry.relative_to(root)).replace("\\", "/")
                    if rel in core or rel in selected or entry.name in _CANDIDATE_EXCLUDE:
                        continue
                    candidates.append({"path": rel, "size": entry.stat().st_size})
                    if len(candidates) >= CANDIDATE_MAX_RESULTS:
                        break
                except OSError:
                    continue

        return {"success": True, "candidates": candidates}
    except Exception as e:
        return {"success": False, "error": f"Failed to list candidates: {str(e)}"}


def get_memory_stats() -> Dict[str, Any]:
    """Get memory statistics.

    Returns:
        Dict with memory stats including item counts by category
    """
    try:
        result = get_memory_items()
        if not result.get("success"):
            return result

        items = result.get("items", [])

        # Count by category
        category_counts = {}
        for item in items:
            cat = item["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Count unprocessed events
        event_path = AGENT_FILE_SYSTEM_PATH / "EVENT_UNPROCESSED.md"
        unprocessed_count = 0
        if event_path.exists():
            content = event_path.read_text(encoding="utf-8")
            # Count lines that look like events
            for line in content.split("\n"):
                if line.strip().startswith("[") and "]" in line:
                    unprocessed_count += 1

        return {
            "success": True,
            "total_items": len(items),
            "category_counts": category_counts,
            "categories": list(category_counts.keys()),
            "unprocessed_events": unprocessed_count,
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to get memory stats: {str(e)}"}
