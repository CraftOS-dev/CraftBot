# -*- coding: utf-8 -*-
"""
agent_core.core.impl.memory.entity_pipeline

The entity-judge pipeline: direct LLM calls + deterministic file writes.

Replaces the entity-indexer skill's agent run. The division of labour is
unchanged — the deterministic matcher establishes every connection and the
LLM only judges pending marks and names new entities — but the judgment is
now a plain single-shot structured completion per batch (records in, JSON
verdicts out) instead of a multi-turn agent loop, and all ENTITIES.md
writes are done by ``MemoryManager.apply_entity_judgments``. The model
never edits the file.

A single invocation converges: new entities minted in one pass attach as
fresh ``?`` candidates on the next graph rebuild and are judged in the
following pass, up to ``ENTITY_JUDGE_MAX_PASSES``.
"""

import json
import re
from typing import Any, Dict, List, Tuple

from agent_core.utils.logger import logger

from agent_core.core.impl.memory.tuning import (
    ENTITY_JUDGE_BATCH_MAX_CHARS,
    ENTITY_JUDGE_BATCH_MAX_RECORDS,
    ENTITY_JUDGE_MAX_PASSES,
    ENTITY_JUDGE_MAX_REASKS,
    ENTITY_JUDGE_THINKING_BUDGET,
)
from agent_core.core.prompts.entity_pipeline import (
    ENTITY_JUDGE_SYSTEM_PROMPT,
    ENTITY_JUDGE_USER_PROMPT,
)

def _batch_records(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split records into call-sized batches by count and summed text size."""
    batches: List[List[Dict[str, Any]]] = []
    batch: List[Dict[str, Any]] = []
    chars = 0
    for record in records:
        size = len(record["text"]) + sum(len(n) for n in record["candidates"])
        if batch and (
            len(batch) >= ENTITY_JUDGE_BATCH_MAX_RECORDS
            or chars + size > ENTITY_JUDGE_BATCH_MAX_CHARS
        ):
            batches.append(batch)
            batch = []
            chars = 0
        batch.append(record)
        chars += size
    if batch:
        batches.append(batch)
    return batches


def _render_records(records: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for record in records:
        candidates = (
            " | ".join(record["candidates"])
            if record["candidates"]
            else "(none — review the text for new entities only)"
        )
        lines.append(f"[{record['id']}] candidates: {candidates}")
        lines.append(f"text: {record['text']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _parse_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Some providers wrap JSON in a markdown fence even in JSON mode.
        stripped = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
        obj = json.loads(stripped)
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON value must be an object")
    return obj


def _validate_response(
    raw: str, batch: List[Dict[str, Any]]
) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """Validate one judge response against its batch's typed contract.

    Returns ``(verdicts, new_entities)`` where verdicts maps chunk id →
    {candidate casefold → "confirm"|"reject"} covering EVERY record and
    EVERY candidate of the batch. Raises ValueError describing the first
    violation — the message is fed back to the model on re-ask.
    """
    obj = _parse_json_object(raw)
    records = obj.get("records")
    new_entities = obj.get("new_entities")
    if not isinstance(records, list):
        raise ValueError('"records" must be a list')
    if not isinstance(new_entities, list) or not all(
        isinstance(n, str) for n in new_entities
    ):
        raise ValueError('"new_entities" must be a list of strings')

    expected = {r["id"]: {c.casefold() for c in r["candidates"]} for r in batch}
    verdicts: Dict[str, Dict[str, str]] = {}
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError('every "records" entry must be an object')
        record_id = entry.get("id")
        if record_id not in expected:
            raise ValueError(f'unknown record id "{record_id}"')
        if record_id in verdicts:
            raise ValueError(f'record id "{record_id}" appears more than once')
        entry_verdicts = entry.get("verdicts")
        if not isinstance(entry_verdicts, list):
            raise ValueError(f'record "{record_id}": "verdicts" must be a list')
        decided: Dict[str, str] = {}
        for verdict_entry in entry_verdicts:
            if not isinstance(verdict_entry, dict):
                raise ValueError(
                    f'record "{record_id}": every verdict must be an object'
                )
            name = str(verdict_entry.get("name", "")).casefold()
            verdict = verdict_entry.get("verdict")
            if name not in expected[record_id]:
                raise ValueError(
                    f'record "{record_id}": "{verdict_entry.get("name")}" '
                    f"is not one of its candidates"
                )
            if verdict not in ("confirm", "reject"):
                raise ValueError(
                    f'record "{record_id}": verdict must be "confirm" or '
                    f'"reject", got "{verdict}"'
                )
            decided[name] = verdict
        missing = expected[record_id] - set(decided)
        if missing:
            raise ValueError(
                f'record "{record_id}": missing verdict(s) for '
                f"{', '.join(sorted(missing))}"
            )
        verdicts[record_id] = decided

    absent = set(expected) - set(verdicts)
    if absent:
        raise ValueError(
            f"missing record id(s): {', '.join(sorted(absent))}"
        )
    return verdicts, [n.strip() for n in new_entities if n.strip()]


async def _judge_batch(
    llm: Any,
    entity_names: List[str],
    batch: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """One judge call for one batch, re-asking on schema violations."""
    user_prompt = ENTITY_JUDGE_USER_PROMPT.format(
        entities="\n".join(entity_names) if entity_names else "(none yet)",
        count=len(batch),
        records=_render_records(batch),
    )
    prompt = user_prompt
    for attempt in range(ENTITY_JUDGE_MAX_REASKS + 1):
        raw = await llm.generate_response_async(
            system_prompt=ENTITY_JUDGE_SYSTEM_PROMPT,
            user_prompt=prompt,
            prompt_name="ENTITY_JUDGE",
            json_mode=True,
            thinking_budget=ENTITY_JUDGE_THINKING_BUDGET,
        )
        try:
            return _validate_response(raw, batch)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(
                f"[ENTITY-JUDGE] Invalid response "
                f"(attempt {attempt + 1}/{ENTITY_JUDGE_MAX_REASKS + 1}): {e}"
            )
            prompt = (
                f"{user_prompt}\n\n"
                f"YOUR PREVIOUS RESPONSE:\n{raw}\n\n"
                f"VALIDATION ERROR:\n{e}\n\n"
                f"Return the corrected JSON object only."
            )
    raise RuntimeError(
        f"entity judge response stayed schema-invalid after "
        f"{ENTITY_JUDGE_MAX_REASKS + 1} attempt(s)"
    )


async def run_entity_judge(memory_manager: Any, llm: Any) -> Dict[str, Any]:
    """Judge all pending connection records; create entities; converge.

    Each pass: collect pending records from the graph, judge them batch by
    batch (each batch's verdicts are applied to ENTITIES.md before the next
    call, so progress persists across failures), then rebuild — entities
    minted this pass surface as fresh ``?`` candidates for the next pass.

    Raises on unrecoverable LLM failure; whatever was applied stays applied
    and the next invocation picks up the remainder.
    """
    # Same guard as the event-stream summarizer: don't pile onto a failing LLM.
    max_failures = getattr(llm, "_max_consecutive_failures", 5)
    if getattr(llm, "consecutive_failures", 0) >= max_failures:
        logger.warning(
            "[ENTITY-JUDGE] Skipping: LLM is in a consecutive-failure state"
        )
        return {"skipped": True}

    stats = {
        "passes": 0,
        "judged_records": 0,
        "flipped": 0,
        "entities_added": 0,
        "remaining_pending": 0,
    }
    for _ in range(ENTITY_JUDGE_MAX_PASSES):
        records = memory_manager.pending_judgment_records()
        if not records:
            break
        stats["passes"] += 1
        entity_names = memory_manager.registry_entity_names()
        logger.info(
            f"[ENTITY-JUDGE] Pass {stats['passes']}: {len(records)} pending "
            f"record(s), {len(entity_names)} known entit"
            f"{'y' if len(entity_names) == 1 else 'ies'}"
        )
        for batch in _batch_records(records):
            verdicts, new_entities = await _judge_batch(llm, entity_names, batch)
            applied = memory_manager.apply_entity_judgments(verdicts, new_entities)
            stats["judged_records"] += len(verdicts)
            stats["flipped"] += applied["flipped"]
            stats["entities_added"] += applied["entities_added"]
            # Later batches of THIS pass judge their pre-rebuild candidates;
            # entities minted here reach them on the next pass's rebuild.
            entity_names = memory_manager.registry_entity_names()

    stats["remaining_pending"] = len(memory_manager.pending_judgment_records())
    logger.info(
        f"[ENTITY-JUDGE] Done: {stats['judged_records']} record(s) judged over "
        f"{stats['passes']} pass(es), {stats['flipped']} mark(s) flipped, "
        f"{stats['entities_added']} entit"
        f"{'y' if stats['entities_added'] == 1 else 'ies'} added, "
        f"{stats['remaining_pending']} still pending"
    )
    return stats
