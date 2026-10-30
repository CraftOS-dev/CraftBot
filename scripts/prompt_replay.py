# -*- coding: utf-8 -*-
"""
Decision replay (prompt audit T0).

Re-sends captured action-selection requests to the configured model, once in
a candidate layout and twice as they were captured, and compares the
decisions. A layout change keeps the agent's behavior when the candidate
agrees with the captured layout about as often as the captured layout agrees
with itself (the model's own run-to-run variance).

Agreement is judged on the decision's action names, order ignored.

Read-only on agent state:
  * only the decision call is made; no action is ever executed;
  * calls go through the base LLM interface without the capture and usage
    hooks, so nothing is written to llm_calls.db or usage.db;
  * by default only requests captured with the configured provider are
    replayed, so no prompt reaches a provider it was not already sent to.

Layouts (``--variant``):
  t1  the decision instructions (<rules> ... </actions>) end the system prompt
      instead of opening the user message (prompt audit T1). Applies to
      requests captured before T1; the text and its order stay the same.

Usage:
    python scripts/prompt_replay.py --dry-run --limit 20
    python scripts/prompt_replay.py --limit 10 --json replay.json
    python scripts/prompt_replay.py --since 14d --max-input 40000 --limit 30
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DECISION_PROMPT = "SELECT_ACTION"
FULL_PROMPT_MARK = "<event_stream>"
# Where the captured (pre-T1) user message ends its decision instructions.
_ACTIONS_HEADER = "<actions>\nThis is the list of action candidates"
_ACTIONS_CLOSE = "\n</actions>"


# ── layouts ──────────────────────────────────────────────────────────────────


def to_t1_layout(system: str, user: str) -> Optional[Tuple[str, str]]:
    """The captured request with its decision instructions moved from the
    start of the user message to the end of the system prompt, joined the
    way the router joins them (decision_system_prompt). None when the user
    message does not open with the instructions (captured after T1)."""
    from agent_core.core.prompts.action import decision_system_prompt

    if not user.lstrip("\n").startswith("<rules>"):
        return None
    header = user.find(_ACTIONS_HEADER)
    if header == -1:
        return None
    close = user.find(_ACTIONS_CLOSE, header)
    if close == -1:
        return None
    end = close + len(_ACTIONS_CLOSE)
    rest = user[end:]
    if not rest.startswith("\n\n"):
        return None
    instructions = user[:end].lstrip("\n")
    return decision_system_prompt(system, instructions), rest[2:]


VARIANTS: Dict[str, Callable[[str, str], Optional[Tuple[str, str]]]] = {
    "t1": to_t1_layout,
}


# ── cases ────────────────────────────────────────────────────────────────────


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    units = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    unit = since[-1].lower()
    if unit not in units:
        raise ValueError(f"--since must end in m/h/d/w (got {since!r})")
    return datetime.now() - timedelta(**{units[unit]: float(since[:-1])})


def load_cases(
    db_path: str,
    *,
    provider: Optional[str],
    since: Optional[datetime],
    max_input: int,
    limit: int,
) -> List[sqlite3.Row]:
    """Full action-selection requests that succeeded, spread evenly over
    their input size (small first calls to large post-fold prompts)."""
    if not os.path.exists(db_path):
        return []
    sql = (
        "SELECT id, timestamp, provider, model, task_id, input_tokens "
        "FROM llm_calls WHERE prompt_name = ? AND status = 'success' "
        "AND input_tokens > 0 AND input_tokens <= ? "
        f"AND instr(user_prompt, '{FULL_PROMPT_MARK}') > 0"
    )
    params: List[Any] = [DECISION_PROMPT, max_input]
    if provider:
        sql += " AND provider = ?"
        params.append(provider)
    if since is not None:
        sql += " AND timestamp >= ?"
        params.append(since.isoformat())
    sql += " ORDER BY input_tokens"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        ids = list(conn.execute(sql, params))
        if limit and len(ids) > limit:
            step = len(ids) / limit
            ids = [ids[int(i * step)] for i in range(limit)]
        out = []
        for meta in ids:
            row = conn.execute(
                "SELECT id, timestamp, provider, model, task_id, input_tokens, "
                "system_prompt, user_prompt, response FROM llm_calls WHERE id = ?",
                (meta["id"],),
            ).fetchone()
            out.append(row)
        return out


# ── decisions ────────────────────────────────────────────────────────────────


def decision_actions(raw: Optional[str]) -> Optional[Tuple[str, ...]]:
    """The action names of a decision reply, sorted; None if unparseable."""
    if not raw or not raw.strip():
        return None
    text = raw.strip().lstrip("﻿")
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except ValueError:
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            start = text.find("{")
            if start != -1:
                try:
                    parsed, _ = json.JSONDecoder().raw_decode(text[start:])
                except ValueError:
                    parsed = None
    if not isinstance(parsed, dict):
        return None
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        actions = [parsed]
    names = [
        str(a.get("action_name", ""))
        for a in actions
        if isinstance(a, dict) and "action_name" in a
    ]
    return tuple(sorted(names)) if names else None


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Self agreement (captured vs captured) against cross agreement
    (candidate vs each captured run)."""
    self_pairs = cross_pairs = self_agree = cross_agree = 0
    unparsed = {"captured": 0, "candidate": 0}
    disagreements = []
    for r in results:
        a1, a2, b = r["captured_1"], r["captured_2"], r["candidate"]
        unparsed["captured"] += (a1 is None) + (a2 is None)
        unparsed["candidate"] += b is None
        if a1 is not None and a2 is not None:
            self_pairs += 1
            self_agree += a1 == a2
        for a in (a1, a2):
            if a is not None and b is not None:
                cross_pairs += 1
                cross_agree += a == b
        if b is not None and b not in (a1, a2):
            disagreements.append({"id": r["id"], "captured": [a1, a2], "candidate": b})
    return {
        "cases": len(results),
        "self_agreement": self_agree / self_pairs if self_pairs else None,
        "cross_agreement": cross_agree / cross_pairs if cross_pairs else None,
        "unparsed": unparsed,
        "disagreements": disagreements,
    }


# ── folds (prompt audit T5) ──────────────────────────────────────────────────
#
# A captured fold's standalone summary call against the summary asked for on
# the session's history (the router's side request), both on the configured
# model. Quality is judged by how many of the folded events' concrete facts
# (paths, URLs, emails, ids, numbers) each summary keeps.

SUMMARY_PROMPT = "EVENT_STREAM_SUMMARIZATION"
_EVENT_LINE = re.compile(r"^\d\d:\d\d:\d\d \[[^\]]+\]: ", re.M)
_FACT = re.compile(
    r"https?://[^\s\"'<>)]+"  # URLs
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"  # emails
    r"|(?:[A-Za-z]:)?[\\/][\w .\\/-]*\.\w{1,6}"  # file paths with an extension
    r"|\b[0-9a-f]{8,}\b"  # hex ids
    r"|\b\d[\d,.]{2,}\d\b"  # numbers of 4+ digits/characters
)


def fold_chunk(cold_prompt: str) -> str:
    """The folded events of a standalone summary prompt."""
    start = cold_prompt.find("OLDEST_EVENTS_CHUNK")
    end = cold_prompt.rfind("</events>")
    return cold_prompt[start:end] if start != -1 and end != -1 else ""


def fold_marker(cold_prompt: str) -> Optional[str]:
    """The last folded event's line, quoted the way the router quotes it."""
    from agent_core.core.impl.action.router import _FOLD_MARKER_CHARS

    chunk = fold_chunk(cold_prompt)
    lines = list(_EVENT_LINE.finditer(chunk))
    if not lines:
        return None
    marker = chunk[lines[-1].start() :].strip()
    if len(marker) > _FOLD_MARKER_CHARS:
        marker = marker[:_FOLD_MARKER_CHARS] + " ..."
    return marker


def facts(text: str) -> Set[str]:
    return {m.group(0).rstrip(".,").lower() for m in _FACT.finditer(text or "")}


def fact_recall(chunk_facts: Set[str], summary: Optional[str]) -> Optional[float]:
    if not chunk_facts or not summary:
        return None
    kept = facts(summary)
    return len(chunk_facts & kept) / len(chunk_facts)


def load_fold_cases(
    db_path: str, *, provider: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    """The latest captured folds whose session history can be rebuilt: the
    session's last full decision request before the fold and every request
    after it, with their replies. A fold whose last event is not in that
    history is skipped (the session could not be told apart)."""
    if not os.path.exists(db_path):
        return []
    full = f"instr(user_prompt, '{FULL_PROMPT_MARK}') > 0"
    cases: List[Dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sql = (
            "SELECT id, timestamp, provider, model, user_prompt, response "
            "FROM llm_calls WHERE prompt_name = ? AND status = 'success'"
        )
        params: List[Any] = [SUMMARY_PROMPT]
        if provider:
            sql += " AND provider = ?"
            params.append(provider)
        for fold in conn.execute(sql + " ORDER BY timestamp DESC", params):
            if len(cases) >= limit:
                break
            marker = fold_marker(fold["user_prompt"])
            last = conn.execute(
                "SELECT task_id FROM llm_calls WHERE prompt_name = ? "
                "AND timestamp < ? AND task_id IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (DECISION_PROMPT, fold["timestamp"]),
            ).fetchone()
            if marker is None or last is None:
                continue
            rows = conn.execute(
                f"SELECT system_prompt, user_prompt, response, {full} AS full_prompt "
                "FROM llm_calls WHERE prompt_name = ? AND task_id = ? "
                "AND timestamp < ? AND status = 'success' ORDER BY timestamp",
                (DECISION_PROMPT, last["task_id"], fold["timestamp"]),
            ).fetchall()
            starts = [i for i, r in enumerate(rows) if r["full_prompt"]]
            if not starts:
                continue
            history = rows[starts[-1] :]
            text = "".join(r["user_prompt"] for r in history)
            if marker[:24] not in text:  # its time and kind, as the model saw it
                continue
            cases.append(
                {
                    "fold": fold,
                    "task_id": last["task_id"],
                    "system": history[-1]["system_prompt"] or "",
                    "history": [
                        (r["user_prompt"], r["response"] or "") for r in history
                    ],
                    "marker": marker,
                }
            )
    return cases


def _summary_on_history(llm, case: Dict[str, Any]) -> Optional[str]:
    """The router's side request, on a session history rebuilt from the log."""
    from agent_core.core.impl.action.router import _summary_from_reply
    from agent_core.core.impl.llm import LLMCallType
    from agent_core.core.prompts import EVENT_STREAM_SUMMARY_ON_HISTORY_PROMPT

    call_type = LLMCallType.ACTION_SELECTION
    task_id = f"replay-{case['fold']['id']}"
    llm.create_session_cache(task_id, call_type, case["system"])
    llm._session_histories[f"{task_id}:{call_type}"] = [
        message
        for user, reply in case["history"]
        for message in (
            {"role": "user", "content": user},
            {"role": "assistant", "content": reply},
        )
    ]
    try:
        raw = llm.generate_side_response_with_session(
            task_id,
            call_type,
            EVENT_STREAM_SUMMARY_ON_HISTORY_PROMPT.format(last_event=case["marker"]),
            case["system"],
        )
    finally:
        llm.end_session_cache(task_id, call_type)
    return _summary_from_reply(raw)


def replay_folds(args, db_path: str, provider: Optional[str]) -> int:
    from agent_core.core.models.registry import session_cc_providers
    from agent_core.utils.token import count_tokens

    cases = load_fold_cases(db_path, provider=provider, limit=args.limit)
    print(f"{len(cases)} folds with a rebuilt session history")
    for case in cases:
        tokens = sum(count_tokens(u) + count_tokens(a) for u, a in case["history"])
        print(
            f"  fold #{case['fold']['id']} ({case['fold']['model']}, "
            f"{case['task_id']}): history {len(case['history'])} turns, "
            f"~{tokens:,} tokens; standalone prompt "
            f"~{count_tokens(case['fold']['user_prompt']):,} tokens"
        )
    if args.dry_run or not cases:
        return 0

    llm = _build_llm()
    # Histories rebuilt here use the plain {"role", "content"} message shape.
    if llm.provider not in session_cc_providers() and llm.provider != "anthropic":
        print(f"Fold replay does not rebuild {llm.provider} histories.")
        return 1

    results = []
    for case in cases:
        fold = case["fold"]
        chunk_facts = facts(fold_chunk(fold["user_prompt"]))
        try:
            standalone = (
                llm.generate_response(
                    user_prompt=fold["user_prompt"], log_response=False, json_mode=False
                )
                or ""
            ).strip()
        except Exception as e:
            standalone = f"[error] {e}"
        try:
            on_history = _summary_on_history(llm, case)
        except Exception as e:
            on_history = f"[error] {e}"
        result = {
            "fold": fold["id"],
            "chunk_facts": len(chunk_facts),
            "standalone": {
                "recall": fact_recall(chunk_facts, standalone),
                "words": len(standalone.split()),
                "text": standalone,
            },
            "on_history": {
                "recall": fact_recall(chunk_facts, on_history),
                "words": len((on_history or "").split()),
                "text": on_history,
            },
        }
        results.append(result)
        fmt = lambda v: "n/a" if v is None else f"{v:.0%}"  # noqa: E731
        print(
            f"  fold #{fold['id']}: {len(chunk_facts)} facts; standalone kept "
            f"{fmt(result['standalone']['recall'])} in "
            f"{result['standalone']['words']} words, on history kept "
            f"{fmt(result['on_history']['recall'])} in "
            f"{result['on_history']['words']} words"
        )

    def mean(key):
        values = [r[key]["recall"] for r in results if r[key]["recall"] is not None]
        return sum(values) / len(values) if values else None

    print(
        f"\nfacts kept, standalone: {mean('standalone')}; on history: "
        f"{mean('on_history')}"
    )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, default=str)
        print(f"Wrote {args.json}")
    return 0


# ── run ──────────────────────────────────────────────────────────────────────


def _build_llm():
    """The configured provider and model, without capture or usage hooks."""
    from agent_core.core.impl.llm import LLMInterface
    from app.config import get_api_key, get_base_url, get_llm_model, get_llm_provider

    provider = get_llm_provider()
    return LLMInterface(
        provider=provider,
        model=get_llm_model(),
        api_key=get_api_key(provider),
        base_url=get_base_url(provider),
    )


def _ask(llm, system: str, user: str) -> Tuple[Optional[Tuple[str, ...]], str]:
    try:
        raw = llm.generate_response(system, user, log_response=False)
    except Exception as e:  # a failed call is a missing sample, not a disagreement
        return None, f"[error] {e}"
    return decision_actions(raw), raw or ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="Replay captured decisions in a new layout."
    )
    ap.add_argument("--db", help="Path to llm_calls.db (default: app data dir).")
    ap.add_argument("--variant", default="t1", choices=sorted(VARIANTS))
    ap.add_argument("--since", help="Only requests newer than e.g. 7d, 24h.")
    ap.add_argument("--limit", type=int, default=10, help="Cases to replay.")
    ap.add_argument(
        "--max-input", type=int, default=60000, help="Skip requests above this input."
    )
    ap.add_argument(
        "--any-provider",
        action="store_true",
        help="Also replay requests captured with other providers.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Build both layouts and count tokens; call no model.",
    )
    ap.add_argument("--json", metavar="PATH", help="Write per-case results as JSON.")
    ap.add_argument(
        "--folds",
        action="store_true",
        help="Replay captured folds: the standalone summary call against the "
        "summary written on the session's history (prompt audit T5).",
    )
    args = ap.parse_args()

    from agent_core.utils.token import count_tokens
    from app.config import APP_DATA_PATH, get_llm_model, get_llm_provider

    db_path = args.db or os.path.join(APP_DATA_PATH, ".usage", "llm_calls.db")
    provider = None if args.any_provider else get_llm_provider()
    if args.folds:
        return replay_folds(args, db_path, provider)
    cases = load_cases(
        db_path,
        provider=provider,
        since=_parse_since(args.since),
        max_input=args.max_input,
        limit=args.limit,
    )
    variant = VARIANTS[args.variant]
    shaped = []
    for row in cases:
        moved = variant(row["system_prompt"] or "", row["user_prompt"])
        if moved is not None:
            shaped.append((row, moved))
    print(
        f"{len(shaped)} cases ({len(cases) - len(shaped)} skipped: not in the "
        f"captured layout) from {provider or 'any provider'}; replaying on "
        f"{get_llm_provider()}/{get_llm_model()}"
    )

    if args.dry_run:
        for row, (system, user) in shaped:
            old_s, old_u = row["system_prompt"] or "", row["user_prompt"]
            same_text = (system + user).replace("\n", "") == (old_s + old_u).replace(
                "\n", ""
            )
            print(
                f"  #{row['id']} {row['model']}: system {count_tokens(old_s)} -> "
                f"{count_tokens(system)}, user {count_tokens(old_u)} -> "
                f"{count_tokens(user)}, same text: {same_text}"
            )
        return 0

    llm = _build_llm()
    results = []
    for n, (row, (system, user)) in enumerate(shaped, 1):
        started = time.monotonic()
        a1, raw_a1 = _ask(llm, row["system_prompt"] or "", row["user_prompt"])
        a2, raw_a2 = _ask(llm, row["system_prompt"] or "", row["user_prompt"])
        b, raw_b = _ask(llm, system, user)
        results.append(
            {
                "id": row["id"],
                "captured_model": row["model"],
                "input_tokens": row["input_tokens"],
                "original": decision_actions(row["response"]),
                "captured_1": a1,
                "captured_2": a2,
                "candidate": b,
                "raw": {"captured_1": raw_a1, "captured_2": raw_a2, "candidate": raw_b},
            }
        )
        print(
            f"  [{n}/{len(shaped)}] #{row['id']} ({row['input_tokens']} tok, "
            f"{time.monotonic() - started:.0f}s): captured {a1} / {a2}, "
            f"{args.variant} {b}"
        )

    summary = summarize(results)
    pct = lambda v: "n/a" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    print(
        f"\nself agreement (captured vs captured): {pct(summary['self_agreement'])}\n"
        f"cross agreement ({args.variant} vs captured): {pct(summary['cross_agreement'])}\n"
        f"unparsed replies: {summary['unparsed']}"
    )
    for d in summary["disagreements"]:
        print(
            f"  differs #{d['id']}: captured {d['captured']} vs {args.variant} {d['candidate']}"
        )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "results": results}, fh, indent=2)
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
