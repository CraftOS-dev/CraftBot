# -*- coding: utf-8 -*-
"""
app.logger

Standard logger for the agent framework. Should be moved to utils
"""

import sys
import os
from datetime import datetime
from loguru import logger as _logger
from app.config import PROJECT_ROOT

_print_level = "INFO"

def define_log_level(print_level="ERROR", logfile_level="DEBUG", name: str = None):
    """
    Configure Loguru logger.
    print_level: console log threshold
    logfile_level: file log threshold
    name: optional prefix for log filename
    """
    global _print_level

    # Ensure logs directory exists
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    # Build filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    log_name = f"{name}_{timestamp}" if name else timestamp
    log_path = logs_dir / f"{log_name}.log"

    # Remove all sinks
    _logger.remove()

    # Console output
    # _logger.add(
    #     sys.stderr,
    #     level=print_level,
    #     backtrace=True,
    #     diagnose=True,
    #     enqueue=True,
    # )

    # File output
    _logger.add(
        log_path,
        level=_print_level,
        backtrace=True,
        diagnose=True,
        enqueue=True,
        rotation="50 MB",
        retention="14 days",
    )

    return _logger


# Create global logger with defaults
logger = define_log_level()
