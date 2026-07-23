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

# Folder for the current process run, e.g. logs/20260629112256/. Holds all.log
# (the full interleaved timeline) plus one sub-folder per session — each named
# by its session id and containing that session's session.log and the log of
# any sub-agent it spawned. Set by define_log_level(); read by the session /
# sub-agent sink helpers below.
_run_log_dir = None

# Local copy of the main session's id (agent_core.core.session.MAIN_SESSION_ID)
# — duplicated here to keep this low-level module import-cycle free.
_MAIN_SESSION_ID = "main"

# session_id -> loguru sink id, so a session's sink can be added idempotently
# and torn down when the session is deleted.
_session_sinks: dict[str, int] = {}

_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{extra[session]: <14} | {extra[agent]: <22} | "
    "{name}:{function}:{line} - {message}"
)

# Per-sub-agent files don't need the session/agent columns — the folder and
# filename already say which session and sub-agent produced them.
_SUBAGENT_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"


def _sanitize(s: str) -> str:
    """Sanitize a string for use as a file/folder name."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "").strip())
    s = re.sub(r"_+", "_", s)
    return s.strip("._-") or "session"


def _session_log_dir(session_id: str):
    """Return (creating if needed) the log folder for a session."""
    session_dir = _run_log_dir / _sanitize(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


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

    # Remove all sinks (and forget the session sinks they backed).
    _logger.remove()
    _session_sinks.clear()

    # Default the context fields so every line carries a session + agent
    # attribution tag. Startup / framework lines default to the main session
    # ("main") and the main agent ("main"). Each session's consumer loop wraps
    # its turns in ``logger.contextualize(session=<id>)`` so every line emitted
    # during a turn — including downstream ActionManager / LLM / action-code
    # logs — is tagged with the session that produced it. The sub-agent runner
    # additionally wraps its run in ``logger.contextualize(agent="sub:...")``.
    _logger.configure(extra={"agent": "main", "session": _MAIN_SESSION_ID})

    # all.log — the full interleaved timeline across every session and every
    # sub-agent, so cross-session / cross-agent ordering isn't lost.
    _logger.add(
        run_dir / "all.log",
        level=_print_level,
        format=_LOG_FORMAT,
        backtrace=True,
        diagnose=True,
        enqueue=True,
        rotation="50 MB",
        retention="14 days",
    )

    # The main session's own folder + sink. Created eagerly so startup /
    # framework lines (which default to session="main") are captured before
    # any session loop starts.
    ensure_session_log_sink(_MAIN_SESSION_ID)

    return _logger


def ensure_session_log_sink(session_id: str):
    """Add a dedicated sink for a session, capturing that session's own lines
    (``extra["session"] == session_id`` and ``extra["agent"] == "main"``, i.e.
    excluding its sub-agents, which get their own files) into
    ``<run>/<session_id>/session.log``.

    Idempotent: a second call for the same session is a no-op, so the session
    loop can call it on every (re)start without stacking sinks.
    """
    if _run_log_dir is None:
        return
    if session_id in _session_sinks:
        return
    try:
        session_dir = _session_log_dir(session_id)
        sink_id = _logger.add(
            session_dir / "session.log",
            level=_print_level,
            format=_LOG_FORMAT,
            filter=lambda record, sid=session_id: (
                record["extra"].get("session") == sid
                and record["extra"].get("agent") == "main"
            ),
            backtrace=True,
            diagnose=True,
            enqueue=True,
            rotation="50 MB",
            retention="14 days",
        )
        _session_sinks[session_id] = sink_id
    except Exception:
        return


def remove_session_log_sink(session_id: str) -> None:
    """Remove a session's sink (added by ``ensure_session_log_sink``). No-op if
    the session has no sink or on errors. Call when a session is deleted."""
    sink_id = _session_sinks.pop(session_id, None)
    if sink_id is None:
        return
    try:
        _logger.remove(sink_id)
    except Exception:
        pass


def add_subagent_log_sink(agent_tag: str, session_id: str | None = None):
    """Add a dedicated file sink capturing ONLY lines tagged with ``agent_tag``
    (set via ``logger.contextualize(agent=...)``). Writes ``<tag>.log`` inside
    the spawning session's folder (``<run>/<session_id>/<tag>.log``) when a
    session id is given, else at the run root. Returns the loguru sink id (or
    None). Pair with ``remove_subagent_log_sink`` in a ``finally`` so the sink
    is dropped when the sub-agent ends."""
    if _run_log_dir is None:
        return None
    base_dir = _session_log_dir(session_id) if session_id else _run_log_dir
    safe = _sanitize(agent_tag)
    try:
        return _logger.add(
            base_dir / f"{safe}.log",
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
