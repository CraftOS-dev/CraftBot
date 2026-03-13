# -*- coding: utf-8 -*-
"""
Action loader for discovering and importing action files.

Walks through specified directories, finds .py files, and dynamically imports them.
Importing triggers the @action decorator, registering them in the registry.
"""
import os
import importlib.util
import sys
from typing import List, Optional
import logging
from pathlib import Path

logger = logging.getLogger("ActionLoader")

# Define default paths relative to the project root to scan for actions
DEFAULT_ACTION_PATHS = [
    os.path.join('core', 'data', 'action'),
]


def load_actions_from_directories(
    base_dir: Optional[str] = None,
    paths_to_scan: Optional[List[str]] = None
):
    """
    Walks through specified directories, finds .py files, and dynamically imports them.
    Importing them triggers the @action decorator, registering them in the registry.

    Args:
        base_dir: Base directory to scan from. Defaults to current working directory.
                  Supports PyInstaller frozen executables (uses sys._MEIPASS).
        paths_to_scan: List of relative paths to scan. Defaults to DEFAULT_ACTION_PATHS.
    """
    if base_dir is None:
        if getattr(sys, 'frozen', False):
            # PyInstaller bundles action files inside the temp _MEIPASS directory
            base_dir = sys._MEIPASS  # type: ignore
        else:
            base_dir = os.getcwd()

    if paths_to_scan is None:
        paths_to_scan = DEFAULT_ACTION_PATHS.copy()
    else:
        paths_to_scan = paths_to_scan + DEFAULT_ACTION_PATHS

    logger.info(f"--- Starting Action Discovery from base: {base_dir} ---")

    count = 0
    processed_files = set()

    for relative_path in paths_to_scan:
        relative_path_obj = Path(relative_path)
        full_search_path = Path(base_dir) / relative_path_obj

        if not os.path.exists(full_search_path):
            logger.debug(f"Skipping non-existent directory: {full_search_path}")
            continue

        logger.debug(f"Scanning directory structure: {full_search_path}")

        # Walk the directory tree
        for root, _, files in os.walk(full_search_path):
            root_path = Path(root)

            # Special handling to only look into 'data/action' if we are scanning the 'agents' folder
            if "agents" in relative_path_obj.parts and "data" in root_path.parts and "action" not in root_path.parts:
                continue

            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    file_path = os.path.join(root, file)

                    # Prevent loading the same file twice if paths overlap
                    if file_path in processed_files:
                        continue
                    processed_files.add(file_path)

                    # Generate a unique module name based on file path to prevent collisions
                    rel_path_from_base = os.path.relpath(file_path, base_dir)
                    module_name_safe = rel_path_from_base.replace(os.path.sep, "_").replace(".", "_").replace("-", "_")

                    try:
                        logger.debug(f"Loading action file: {rel_path_from_base}")
                        # Dynamic Import
                        spec = importlib.util.spec_from_file_location(module_name_safe, file_path)
                        if spec and spec.loader:
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[module_name_safe] = module
                            spec.loader.exec_module(module)
                            count += 1
                    except Exception as e:
                        logger.error(f"Failed to load action script {file_path}: {e}", exc_info=True)

    logger.info(f"--- Action Discovery Complete. Processed {count} files. ---")

    # Startup requirement installation is disabled by default for faster boot times.
    # Requirements are installed just-in-time (JIT) before action execution via
    # _ensure_requirements() in executor.py. To re-enable startup installation,
    # set environment variable: INSTALL_REQUIREMENTS_AT_STARTUP=true
    if os.getenv("INSTALL_REQUIREMENTS_AT_STARTUP", "false").lower() == "true":
        from agent_core.core.action_framework.registry import install_all_action_requirements
        install_all_action_requirements()
    else:
        logger.debug("Skipping startup requirement installation (JIT mode enabled). "
                     "Requirements will be installed before action execution.")
