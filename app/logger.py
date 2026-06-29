# -*- coding: utf-8 -*-
"""
app.logger

Standard logger for the agent framework. Should be moved to utils
"""

import re
from datetime import datetime
from loguru import logger as _logger
from app.config import PROJECT_ROOT

_print_level = "INFO"

# Folder for the current process run, e.g. logs/20260629112256/. Holds main.log,
# all.log, and one file per sub-agent. Set by define_log_level(); read by
# add_subagent_log_sink().
_run_log_dir = None


def define_log_level(print_level="ERROR", logfile_level="DEBUG", name: str = None):
    """
    Configure Loguru logger.
    print_level: console log threshold
    logfile_level: file log threshold
    name: optional prefix for log filename
    """
    global _print_level, _run_log_dir

    # One folder per process run: logs/<name_>?<timestamp>/
    logs_dir = PROJECT_ROOT / "logs"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    run_name = f"{name}_{timestamp}" if name else timestamp
    run_dir = logs_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    _run_log_dir = run_dir

    # Remove all sinks
    _logger.remove()

    # Default the `agent` context field so every line carries an attribution
    # tag. The main agent's lines show "main"; the sub-agent runner wraps its
    # run in ``logger.contextualize(agent="sub:<type>:<id>")`` so EVERY line it
    # emits — including downstream ActionManager / LLM / action-code logs — is
    # tagged with the sub-agent that produced it. Each agent also gets its own
    # file (main.log / sub_<type>_<id>.log); all.log keeps the full timeline.
    _logger.configure(extra={"agent": "main"})

    log_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{extra[agent]: <22} | {name}:{function}:{line} - {message}"
    )

    # main.log — only lines tagged "main" (the main agent + framework/startup,
    # i.e. anything not running inside a sub-agent's contextualize block).
    _logger.add(
        run_dir / "main.log",
        level=_print_level,
        format=log_format,
        filter=lambda record: record["extra"].get("agent") == "main",
        backtrace=True,
        diagnose=True,
        enqueue=True,
        rotation="50 MB",
        retention="14 days",
    )

    # all.log — the full interleaved timeline across the main agent and every
    # sub-agent, so cross-agent ordering isn't lost.
    _logger.add(
        run_dir / "all.log",
        level=_print_level,
        format=log_format,
        backtrace=True,
        diagnose=True,
        enqueue=True,
        rotation="50 MB",
        retention="14 days",
    )

    return _logger


# Per-sub-agent files don't need the agent column — the filename already says it.
_SUBAGENT_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
)


def add_subagent_log_sink(agent_tag: str):
    """Add a dedicated file sink capturing ONLY lines tagged with ``agent_tag``
    (set via ``logger.contextualize(agent=...)``). Writes ``<run>/<tag>.log``.
    Returns the loguru sink id (or None). Pair with ``remove_subagent_log_sink``
    in a ``finally`` so the sink is dropped when the sub-agent ends."""
    if _run_log_dir is None:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", agent_tag)
    try:
        return _logger.add(
            _run_log_dir / f"{safe}.log",
            level=_print_level,
            format=_SUBAGENT_FORMAT,
            filter=lambda record, tag=agent_tag: record["extra"].get("agent") == tag,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )
    except Exception:
        return None


def remove_subagent_log_sink(sink_id) -> None:
    """Remove a sink added by ``add_subagent_log_sink`` (no-op on None/errors)."""
    if sink_id is None:
        return
    try:
        _logger.remove(sink_id)
    except Exception:
        pass


# Create global logger with defaults
logger = define_log_level()
