# -*- coding: utf-8 -*-
"""TurnEngine — the one DECIDE phase for every agentic loop.

Previously implemented twice with identical intent:
- router ``_prompt_for_decision`` session branch (:697-768) for tasks;
- runner ``_build_user_prompt`` + ``_ask_llm_for_decision`` (:390-504) for
  sub-agents.

One turn's decide phase =
  1. session-delta orchestration: if this session has synced before, send
     ONLY the event-stream delta; no delta (summarization rolled events past
     the sync point) → end the provider session, reset the sync point, and
     re-establish with the full first prompt;
  2. LLM call through the provider session cache;
  3. parse via the caller's parser profile;
  4. on parse/provider failure: retry (max 3) with the caller's feedback
     augmenter, sending the augmented prompt through the live session —
     [normalized behavior] the old router path instead reset the whole
     session on a parse-failure retry (an accident of its loop structure,
     strictly more expensive; the suites don't pin it);
  5. ``LLMConsecutiveFailureError`` always re-raises immediately — fatal
     policy belongs to the driver.

Scheduling (WHEN turns happen), execution policy (parallel vs serial,
caps, exit gates, limits, persistence) and context CONTENT (what the
prompts say) remain with the drivers — they are configuration, passed in
via :class:`DecideConfig`.

Step-program consultation happens BEFORE this phase, in the shared turn
skeleton (:mod:`app.agentic.loop`) — by the time ``decide`` runs, code has
already declined the turn (or bounded it with an "llm" step directive).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple, Union

from app.agentic._log import logger

MAX_DECIDE_RETRIES = 3

# Canonical marker a driver stamps into a sub-agent's RESULT when the run
# died of LLM INFRASTRUCTURE failure (provider outage, exhausted credits) —
# not of the work itself. Outcome recorders treat marked results as
# "infrastructure down: pause, do NOT burn round/check budget"
INFRA_LLM_MARKER = "[INFRA:LLM_UNAVAILABLE]"


def augment_retry_with_feedback(
    base_prompt: str, attempt: int, raw_response: str, error_message: str
) -> str:
    """Default parse-retry augmenter: names the failure and ECHOES the raw
    response so the model can see and correct its own mistake. Generic
    wording — the required shape is whatever the base prompt's output
    contract already specifies."""
    return (
        f"{base_prompt}\n\n"
        f"PREVIOUS ATTEMPT {attempt} FAILED TO PARSE: {error_message}\n"
        "Review your last reply (shown below in RAW RESPONSE) and return "
        "ONLY the corrected JSON object in exactly the format the "
        "instructions specify — no commentary, no code fences.\n\n"
        "RAW RESPONSE:\n"
        f"{raw_response}\n"
        "--- End of RAW RESPONSE ---"
    )


def append_step_directive(prompt: str, directive: Optional[str]) -> str:
    """Append a step program's "llm" directive to a turn prompt.

    Rides AFTER the prompt body so it's the last thing the model reads
    before deciding. Shared by both drivers — the task router's delta
    turns and the sub-agent runner's first/delta prompts."""
    if not directive:
        return prompt
    return f"{prompt}\n\n<step_directive>\n{directive}\n</step_directive>"


@dataclass
class DecideConfig:
    """Everything caller-specific about one decide phase."""

    session_key: str  # task_id or sub_id (provider session)
    call_type: str  # LLMCallType.*
    system_prompt: str  # stable session prefix
    # Full user prompt for establish/re-establish turns. May be a zero-arg
    # CALLABLE: delta turns never consume it, so lazy callers avoid building
    # a large prompt (query + full event log) only to discard it.
    first_prompt: Union[str, Callable[[], str]]
    # delta events -> the user prompt for a delta turn (identity for tasks,
    # wrapped with plan block + nudge for sub-agents)
    delta_prompt_builder: Callable[[str], str] = field(default=lambda d: d)
    # raw LLM text -> (decision, error). Decision shape is caller-defined.
    parse: Callable[[str], Tuple[Optional[Any], Optional[str]]] = field(
        default=lambda raw: (None, "no parser configured")
    )
    # (base_prompt, attempt_no, raw_response, error) -> augmented retry prompt
    augment_retry: Callable[[str, int, str, str], str] = field(
        default=augment_retry_with_feedback
    )
    prompt_name: Optional[str] = None
    max_retries: int = MAX_DECIDE_RETRIES
    # exhaustion policy: "raise" (task driver) or "none" → return (None, err)
    on_exhaust: str = "raise"


async def decide(
    llm_interface: Any,
    stream: Any,
    cfg: DecideConfig,
) -> Tuple[Optional[Any], Optional[str]]:
    """Run one decide phase. Returns (decision, None) on success.

    On exhaustion: raises the last error when ``cfg.on_exhaust == "raise"``,
    else returns (None, error_text). ``LLMConsecutiveFailureError`` always
    propagates immediately (fatal — driver policy decides what dying means).
    """
    from agent_core.core.impl.llm import LLMConsecutiveFailureError

    base_prompt = _build_turn_prompt(llm_interface, stream, cfg)
    current_prompt = base_prompt
    last_error: Optional[str] = None
    last_raw: Optional[str] = None
    last_exc: Optional[Exception] = None

    for attempt in range(1, cfg.max_retries + 1):
        try:
            raw = await llm_interface.generate_response_with_session_async(
                task_id=cfg.session_key,
                call_type=cfg.call_type,
                user_prompt=current_prompt,
                system_prompt_for_new_session=cfg.system_prompt,
                prompt_name=cfg.prompt_name,
            )
        except LLMConsecutiveFailureError:
            raise  # fatal — never retried, driver decides the funeral
        except Exception as e:
            logger.error(
                f"[AGENTIC:DECIDE] {cfg.session_key} LLM call failed on "
                f"attempt {attempt}: {e}"
            )
            last_error = f"LLM call failed: {e}"
            last_exc = e
            current_prompt = cfg.augment_retry(
                base_prompt,
                attempt,
                f"[LLM ERROR] {e}",
                "LLM provider failed - retrying",
            )
            continue

        last_raw = raw or ""
        decision, parse_error = cfg.parse(raw)
        if decision is not None:
            # Advance the sync point so the next turn's delta excludes
            # everything up to and including this turn's outcome.
            if stream is not None:
                try:
                    stream.mark_session_synced(cfg.call_type)
                except Exception:
                    pass
            return decision, None

        last_error = parse_error or "unknown parse error"
        logger.warning(
            f"[AGENTIC:DECIDE] {cfg.session_key} parse error attempt "
            f"{attempt}: {last_error} | raw={str(raw)[:300]!r}"
        )
        current_prompt = cfg.augment_retry(base_prompt, attempt, last_raw, last_error)

    exhausted = f"{last_error} (last raw response: {str(last_raw)[:500]!r})"
    if cfg.on_exhaust == "raise":
        if last_exc is not None and last_error and "LLM call failed" in last_error:
            raise RuntimeError(
                f"Unable to generate action decision after {cfg.max_retries} "
                f"attempts: {last_exc}. Check LLM configuration, API "
                "credentials, and service availability."
            )
        raise ValueError(
            f"Unable to parse action decision after {cfg.max_retries} "
            f"attempts: {exhausted}"
        )
    return None, exhausted


def _build_turn_prompt(llm_interface: Any, stream: Any, cfg: DecideConfig) -> str:
    """Session-delta orchestration: returns the turn's user prompt.

    First turn (or after a reset): the full first prompt establishes the
    provider session. Delta turns: only events appended since the sync
    point. No delta while synced = summarization rolled events past the
    sync point → end the provider session + reset the sync point + resend
    the full prompt (the only path that re-grounds the model after cached
    history vanishes)."""
    def _first() -> str:
        fp = cfg.first_prompt
        return fp() if callable(fp) else fp

    if stream is None or not stream.has_session_sync(cfg.call_type):
        return _first()

    delta_str, has_delta = stream.get_delta_events(cfg.call_type)
    if not has_delta:
        logger.info(
            f"[AGENTIC:DECIDE] {cfg.session_key} no delta events / "
            "summarization detected — resetting session and resending full prompt"
        )
        try:
            llm_interface.end_session_cache(cfg.session_key, cfg.call_type)
        except Exception:
            pass
        try:
            stream.reset_session_sync(cfg.call_type)
        except Exception:
            pass
        return _first()

    return cfg.delta_prompt_builder(delta_str)
