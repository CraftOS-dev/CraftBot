"""Memory settings management for UI layer.

Provides functions for managing memory mode and memory items
that can be used by any interface adapter (Browser, TUI, CLI).
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    SETTINGS_CONFIG_PATH,
)


# Memory item regex pattern: [YYYY-MM-DD HH:MM:SS] [category] content
MEMORY_ITEM_PATTERN = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+\[(\w+)\]\s+(.+)$'
)


# ─────────────────────────────────────────────────────────────────────
# Memory Mode Control
# ─────────────────────────────────────────────────────────────────────

def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    if not SETTINGS_CONFIG_PATH.exists():
        return {
            "proactive": {"enabled": True},
            "memory": {"enabled": True},
            "general": {"agent_name": "CraftBot"}
        }

    try:
        with open(SETTINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "proactive": {"enabled": True},
            "memory": {"enabled": True},
            "general": {"agent_name": "CraftBot"}
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


def get_memory_mode() -> Dict[str, Any]:
    """Get the current memory mode status.

    Returns:
        Dict with 'success' and 'enabled' fields.
    """
    try:
        enabled = is_memory_enabled()
        return {
            "success": True,
            "enabled": enabled
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get memory mode: {str(e)}"
        }


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
        return {
            "success": False,
            "error": f"Failed to set memory mode: {str(e)}"
        }


# ─────────────────────────────────────────────────────────────────────
# Memory Items Management
# ─────────────────────────────────────────────────────────────────────

def _parse_memory_items(content: str) -> List[Dict[str, Any]]:
    """Parse memory items from MEMORY.md content.

    Args:
        content: Raw content of MEMORY.md

    Returns:
        List of memory item dictionaries with timestamp, category, content
    """
    items = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        match = MEMORY_ITEM_PATTERN.match(line)
        if match:
            timestamp_str, category, item_content = match.groups()
            items.append({
                "id": f"mem_{i}_{hash(line) & 0xFFFFFFFF:08x}",
                "timestamp": timestamp_str,
                "category": category.lower(),
                "content": item_content,
                "raw": line
            })

    return items


def _serialize_memory_items(items: List[Dict[str, Any]]) -> str:
    """Serialize memory items back to MEMORY.md format.

    Args:
        items: List of memory item dictionaries

    Returns:
        Formatted memory items string
    """
    lines = []
    for item in items:
        line = f"[{item['timestamp']}] [{item['category']}] {item['content']}"
        lines.append(line)
    return '\n'.join(lines)


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
        header = content[:idx + len(memory_section_marker)]
        items_section = content[idx + len(memory_section_marker):]
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
            cat = item['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)

        return {
            "success": True,
            "items": items,
            "categories": list(categories.keys()),
            "count": len(items)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get memory items: {str(e)}"
        }


def add_memory_item(
    category: str,
    content: str,
    timestamp: Optional[str] = None
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

        # Create new item
        new_line = f"[{timestamp}] [{category.lower()}] {content}"
        new_item = {
            "id": f"mem_{len(items)}_{hash(new_line) & 0xFFFFFFFF:08x}",
            "timestamp": timestamp,
            "category": category.lower(),
            "content": content,
            "raw": new_line
        }

        items.append(new_item)

        # Write back
        items_content = _serialize_memory_items(items)
        if _write_memory_file(header, items_content):
            return {
                "success": True,
                "item": new_item
            }
        else:
            return {
                "success": False,
                "error": "Failed to write memory file"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to add memory item: {str(e)}"
        }


def update_memory_item(
    item_id: str,
    category: Optional[str] = None,
    content: Optional[str] = None
) -> Dict[str, Any]:
    """Update an existing memory item.

    Args:
        item_id: The item ID to update
        category: New category (optional)
        content: New content (optional)

    Returns:
        Dict with 'success', 'item' or 'error' fields
    """
    try:
        header, items_section = _read_memory_file()
        items = _parse_memory_items(items_section)

        # Find the item
        item_found = None
        for item in items:
            if item['id'] == item_id:
                item_found = item
                break

        if not item_found:
            return {
                "success": False,
                "error": f"Memory item not found: {item_id}"
            }

        # Update fields
        if category is not None:
            item_found['category'] = category.lower()
        if content is not None:
            item_found['content'] = content

        # Update raw
        item_found['raw'] = f"[{item_found['timestamp']}] [{item_found['category']}] {item_found['content']}"

        # Write back
        items_content = _serialize_memory_items(items)
        if _write_memory_file(header, items_content):
            return {
                "success": True,
                "item": item_found
            }
        else:
            return {
                "success": False,
                "error": "Failed to write memory file"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update memory item: {str(e)}"
        }


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
        items = [item for item in items if item['id'] != item_id]

        if len(items) == original_count:
            return {
                "success": False,
                "error": f"Memory item not found: {item_id}"
            }

        # Write back
        items_content = _serialize_memory_items(items)
        if _write_memory_file(header, items_content):
            return {"success": True}
        else:
            return {
                "success": False,
                "error": "Failed to write memory file"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to remove memory item: {str(e)}"
        }


def reset_memory() -> Dict[str, Any]:
    """Reset MEMORY.md by restoring from template.

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / "MEMORY.md"
    target_path = AGENT_FILE_SYSTEM_PATH / "MEMORY.md"

    try:
        if not template_path.exists():
            return {
                "success": False,
                "error": "MEMORY.md template not found"
            }

        # Copy template to target
        shutil.copy(template_path, target_path)

        # Read restored content
        content = target_path.read_text(encoding="utf-8")

        return {
            "success": True,
            "content": content
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to reset memory: {str(e)}"
        }


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
            "error": f"Failed to clear unprocessed events: {str(e)}"
        }


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
            cat = item['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Count unprocessed events
        event_path = AGENT_FILE_SYSTEM_PATH / "EVENT_UNPROCESSED.md"
        unprocessed_count = 0
        if event_path.exists():
            content = event_path.read_text(encoding="utf-8")
            # Count lines that look like events
            for line in content.split('\n'):
                if line.strip().startswith('[') and ']' in line:
                    unprocessed_count += 1

        return {
            "success": True,
            "total_items": len(items),
            "category_counts": category_counts,
            "categories": list(category_counts.keys()),
            "unprocessed_events": unprocessed_count
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get memory stats: {str(e)}"
        }
