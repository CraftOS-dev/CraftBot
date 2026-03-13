# -*- coding: utf-8 -*-
"""
Configurable logger for the agent framework.

This module provides a shared logger that can be configured by CraftBot
with its specific settings.

Usage:
    # At project startup, configure the logger:
    from agent_core.utils.logger import configure_logging
    from pathlib import Path

    configure_logging(
        project_root=Path("/path/to/project"),
        log_level="INFO",
        name="craftbot"
    )

    # Then import and use the logger anywhere:
    from agent_core.utils.logger import logger
    logger.info("Something happened")
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger as _loguru_logger

# Configuration state
_configured = False
_log_level = "INFO"
_project_root: Optional[Path] = None


def configure_logging(
    project_root: Path,
    log_level: str = "INFO",
    name: Optional[str] = None,
    console_output: bool = False,
    rotation: str = "50 MB",
    retention: str = "14 days",
) -> None:
    """
    Configure the shared logger for the current project.

    This should be called once at project startup before any logging occurs.
    It sets up file logging with rotation and optionally console output.

    Args:
        project_root: Root directory of the project (logs will be in project_root/logs/)
        log_level: Logging threshold level (DEBUG, INFO, WARN, ERROR)
        name: Optional prefix for log filename
        console_output: Whether to also log to console (stderr)
        rotation: Log file rotation size (default: "50 MB")
        retention: Log file retention period (default: "14 days")
    """
    global _configured, _log_level, _project_root

    _log_level = log_level
    _project_root = project_root

    # Ensure logs directory exists
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Build filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    log_name = f"{name}_{timestamp}" if name else timestamp
    log_path = logs_dir / f"{log_name}.log"

    # Remove all existing sinks
    _loguru_logger.remove()

    # Console output (optional)
    if console_output:
        _loguru_logger.add(
            sys.stderr,
            level=log_level,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )

    # File output
    _loguru_logger.add(
        log_path,
        level=log_level,
        backtrace=True,
        diagnose=True,
        enqueue=True,
        rotation=rotation,
        retention=retention,
    )

    _configured = True


def define_log_level(
    print_level: str = "ERROR",
    logfile_level: str = "DEBUG",
    name: Optional[str] = None,
):
    """
    Legacy function for backward compatibility.

    Configure Loguru logger with the specified levels.
    Note: This requires project_root to be set via configure_logging first,
    or it will use the current working directory.

    Args:
        print_level: Console log threshold (currently unused - console disabled)
        logfile_level: File log threshold
        name: Optional prefix for log filename

    Returns:
        The configured logger instance
    """
    global _log_level, _project_root

    # Use configured project root or fall back to cwd
    project_root = _project_root or Path.cwd()

    # Ensure logs directory exists
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Build filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    log_name = f"{name}_{timestamp}" if name else timestamp
    log_path = logs_dir / f"{log_name}.log"

    # Remove all sinks
    _loguru_logger.remove()

    # File output only (console disabled as in original)
    _loguru_logger.add(
        log_path,
        level=_log_level,
        backtrace=True,
        diagnose=True,
        enqueue=True,
        rotation="50 MB",
        retention="14 days",
    )

    return _loguru_logger


# Export the logger instance
# Projects should call configure_logging() at startup to set up proper paths
logger = _loguru_logger
