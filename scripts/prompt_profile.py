# -*- coding: utf-8 -*-
"""
Prompt profiler (issue #322, P2).

Aggregates the captured `llm_calls` table per (prompt_name, provider, model) and
reports the efficiency picture for each named prompt on real traffic: latency
(p50/p95), token volume, and cache hit-ratio. No pricing (we keep no per-model
price table); rank prompts by token volume as the cost proxy.

The data comes from the capture substrate (P1) — see
docs/design/prompt-optimization.md. This is a read-only view; it never writes to
the agent's databases.

Prompt-audit views (read-only, same data):

    --sections     tokens per prompt block (<rules>, <actions>, <event_stream>,
                   ...) of the full action-selection prompts, per layout.
    --cache        how much of the action-selection input the provider served
                   from cache, per model: full prompts (a session history's
                   first request) apart from deltas (its later requests), and
                   the deltas that missed.
    --duplication  how often a long parameter value from a decision comes back
                   in the next delta (inputs the model already wrote, sent
                   again as action_start events).
    --resets       action-selection requests by kind (full, delta, correction,
                   stateless), and full requests by why their session history
                   started anew (first, fold, skill, restart, ...).

Usage:
    python scripts/prompt_profile.py                       # all captured calls
    python scripts/prompt_profile.py --since 24h           # last 24 hours
    python scripts/prompt_profile.py --md report.md --json report.json
    python scripts/prompt_profile.py --db path/to/llm_calls.db
    python scripts/prompt_profile.py --sections --since 7d
    python scripts/prompt_profile.py --cache --since 14d
    python scripts/prompt_profile.py --duplication --since 7d
    python scripts/prompt_profile.py --resets --since 7d
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Make the repo root importable when run directly.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _default_db_path() -> str:
    from app.config import APP_DATA_PATH

    return os.path.join(APP_DATA_PATH, ".usage", "llm_calls.db")


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    """Parse a relative window like '24h', '7d', '90m' into a cutoff datetime."""
    if not since:
        return None
    units = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    unit = since[-1].lower()
    if unit not in units:
        raise ValueError(f"--since must end in m/h/d/w (got {since!r})")
    qty = float(since[:-1])
    return datetime.now() - timedelta(**{units[unit]: qty})


def _percentile(sorted_vals: List[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0,1]) of a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(sorted_vals[int(k)])
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def load_rows(db_path: str, since: Optional[datetime]) -> List[sqlite3.Row]:
    if not os.path.exists(db_path):
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sql = (
            "SELECT prompt_name, provider, model, call_type, latency_ms, "
            "input_tokens, output_tokens, cached_tokens, status, timestamp "
            "FROM llm_calls"
        )
        params: tuple = ()
        if since is not None:
            sql += " WHERE timestamp >= ?"
            params = (since.isoformat(),)
        return list(conn.execute(sql, params).fetchall())


def aggregate(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    groups: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "errors": 0,
            "latencies": [],
            "input": 0,
            "output": 0,
            "cached": 0,
        }
    )
    for r in rows:
        key = (r["prompt_name"] or "(untagged)", r["provider"] or "", r["model"] or "")
        g = groups[key]
        g["calls"] += 1
        if r["status"] != "success":
            g["errors"] += 1
        g["latencies"].append(r["latency_ms"] or 0)
        g["input"] += r["input_tokens"] or 0
        g["output"] += r["output_tokens"] or 0
        g["cached"] += r["cached_tokens"] or 0

    out: List[Dict[str, Any]] = []
    for (prompt_name, provider, model), g in groups.items():
        lat = sorted(g["latencies"])
        calls = g["calls"]
        out.append(
            {
                "prompt_name": prompt_name,
                "provider": provider,
                "model": model,
                "calls": calls,
                "errors": g["errors"],
                "latency_p50_ms": round(_percentile(lat, 0.50)),
                "latency_p95_ms": round(_percentile(lat, 0.95)),
                "avg_input_tokens": round(g["input"] / calls),
                "avg_output_tokens": round(g["output"] / calls),
                "cache_hit_ratio": (g["cached"] / g["input"]) if g["input"] else 0.0,
                "total_input_tokens": g["input"],
                "total_output_tokens": g["output"],
            }
        )
    # No price table, so rank by total input tokens (the cost proxy).
    out.sort(key=lambda d: d["total_input_tokens"], reverse=True)
    return out


def _fmt_table(agg: List[Dict[str, Any]]) -> str:
    headers = [
        ("prompt_name", "PROMPT", "l"),
        ("model", "MODEL", "l"),
        ("calls", "CALLS", "r"),
        ("latency_p50_ms", "p50ms", "r"),
        ("latency_p95_ms", "p95ms", "r"),
        ("avg_input_tokens", "AVG_IN", "r"),
        ("avg_output_tokens", "AVG_OUT", "r"),
        ("cache_hit_ratio", "CACHE%", "r"),
        ("total_input_tokens", "TOT_IN", "r"),
        ("total_output_tokens", "TOT_OUT", "r"),
    ]

    def cell(row: Dict[str, Any], key: str) -> str:
        v = row[key]
        if key == "cache_hit_ratio":
            return f"{v * 100:.0f}%"
        return str(v)

    widths = {
        key: max(len(label), *(len(cell(r, key)) for r in agg)) if agg else len(label)
        for key, label, _ in headers
    }
    lines = []
    head = "  ".join(
        label.ljust(widths[key]) if align == "l" else label.rjust(widths[key])
        for key, label, align in headers
    )
    lines.append(head)
    lines.append("-" * len(head))
    for r in agg:
        lines.append(
            "  ".join(
                cell(r, key).ljust(widths[key])
                if align == "l"
                else cell(r, key).rjust(widths[key])
                for key, _, align in headers
            )
        )
    return "\n".join(lines)


def _totals(agg: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "groups": len(agg),
        "calls": sum(r["calls"] for r in agg),
        "total_input_tokens": sum(r["total_input_tokens"] for r in agg),
        "total_output_tokens": sum(r["total_output_tokens"] for r in agg),
    }


def _markdown(agg: List[Dict[str, Any]], totals: Dict[str, Any]) -> str:
    cols = [
        "prompt_name",
        "model",
        "calls",
        "latency_p50_ms",
        "latency_p95_ms",
        "avg_input_tokens",
        "avg_output_tokens",
        "cache_hit_ratio",
        "total_input_tokens",
        "total_output_tokens",
    ]
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for r in agg:
        cells = []
        for c in cols:
            v = r[c]
            if c == "cache_hit_ratio":
                cells.append(f"{v * 100:.0f}%")
            else:
                cells.append(str(v))
        body.append("| " + " | ".join(cells) + " |")
    summary = (
        f"\n**Totals:** {totals['calls']} calls across {totals['groups']} "
        f"prompt/model groups, {totals['total_input_tokens']} input / "
        f"{totals['total_output_tokens']} output tokens.\n"
    )
    return "# Prompt profile\n\n" + "\n".join([head, sep, *body]) + "\n" + summary


# ── Prompt-audit views ────────────────────────────────────────────────────────

DECISION_PROMPT = "SELECT_ACTION"
# A full action-selection prompt carries the rendered stream in this block; a
# delta (a session history's later request) is bare event lines.
FULL_PROMPT_MARK = "<event_stream>"
# Below this share of its input served from cache, a delta counts as a miss.
MISS_RATIO = 0.5
# Parameter values at least this long are checked for a resend; the first
# _PROBE_CHARS characters identify them.
LONG_PARAM_CHARS = 200
_PROBE_CHARS = 120

_OPEN_TAG = re.compile(r"^<([a-z_]+)>", re.M)


def split_sections(text: str) -> List[Tuple[str, str]]:
    """The top-level ``<tag>...</tag>`` blocks of a prompt, in order.

    A block opens with a tag at the start of a line and runs to its closing
    tag. Text outside every block comes back as ``(other)`` (whitespace-only
    gaps are dropped); an opening tag without a close runs to the end.
    """
    sections: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _OPEN_TAG.search(text, pos)
        if match is None:
            break
        if text[pos : match.start()].strip():
            sections.append(("(other)", text[pos : match.start()]))
        name = match.group(1)
        close = text.find(f"</{name}>", match.end())
        end = len(text) if close == -1 else close + len(name) + 3
        sections.append((name, text[match.start() : end]))
        pos = end
    if text[pos:].strip():
        sections.append(("(other)", text[pos:]))
    return sections


def _decision_rows(
    db_path: str,
    since: Optional[datetime],
    columns: str,
    where: str = "",
    order: str = "timestamp",
    limit: Optional[int] = None,
) -> Iterable[sqlite3.Row]:
    """Captured action-selection calls with input, streamed in ``order``."""
    if not os.path.exists(db_path):
        return
    sql = (
        f"SELECT {columns} FROM llm_calls WHERE prompt_name = ? "
        f"AND input_tokens > 0 {where}"
    )
    params: List[Any] = [DECISION_PROMPT]
    if since is not None:
        sql += " AND timestamp >= ?"
        params.append(since.isoformat())
    sql += f" ORDER BY {order}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield from conn.execute(sql, params)
    finally:
        conn.close()


def section_report(
    db_path: str, since: Optional[datetime], limit: int = 50
) -> List[Dict[str, Any]]:
    """Average tokens per prompt block over the latest ``limit`` full
    action-selection prompts, per layout ("rules in system" once the decision
    instructions end the system prompt, "rules in user" before)."""
    from agent_core.utils.token import count_tokens

    rows = _decision_rows(
        db_path,
        since,
        "system_prompt, user_prompt",
        f"AND instr(user_prompt, '{FULL_PROMPT_MARK}') > 0",
        order="timestamp DESC",
        limit=limit,
    )
    layouts: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        parts = (("system", row["system_prompt"] or ""), ("user", row["user_prompt"]))
        split = {part: split_sections(text) for part, text in parts}
        in_system = any(name == "rules" for name, _ in split["system"])
        layout = layouts.setdefault(
            "rules in system" if in_system else "rules in user",
            {"rows": 0, "blocks": defaultdict(int), "order": []},
        )
        layout["rows"] += 1
        for part, sections in split.items():
            for name, block in sections:
                key = (part, name)
                if key not in layout["blocks"]:
                    layout["order"].append(key)
                layout["blocks"][key] += count_tokens(block)

    report = []
    for name, layout in layouts.items():
        n = layout["rows"]
        blocks = [
            {
                "part": part,
                "block": block,
                "avg_tokens": round(layout["blocks"][(part, block)] / n),
            }
            for part, block in layout["order"]
        ]
        total = sum(b["avg_tokens"] for b in blocks) or 1
        for b in blocks:
            b["share"] = b["avg_tokens"] / total
        report.append(
            {
                "layout": name,
                "rows": n,
                "avg_total_tokens": total,
                "avg_system_tokens": sum(
                    b["avg_tokens"] for b in blocks if b["part"] == "system"
                ),
                "blocks": blocks,
            }
        )
    return report


def cache_report(db_path: str, since: Optional[datetime]) -> List[Dict[str, Any]]:
    """Action-selection input served from cache, per model and request kind.

    ``full``: the whole prompt (a history's first request, or after a fold or
    reset). ``delta``: a history's later request; ``misses`` counts deltas
    with under MISS_RATIO of their input cached, and the uncached tokens they
    carried.
    """
    groups: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "input": 0, "cached": 0, "misses": 0, "miss_uncached": 0}
    )
    columns = (
        "provider, model, input_tokens, cached_tokens, "
        f"instr(user_prompt, '{FULL_PROMPT_MARK}') > 0 AS full_prompt"
    )
    for row in _decision_rows(db_path, since, columns):
        kind = "full" if row["full_prompt"] else "delta"
        g = groups[(f"{row['provider']}/{row['model']}", kind)]
        inp, cached = row["input_tokens"], row["cached_tokens"] or 0
        g["calls"] += 1
        g["input"] += inp
        g["cached"] += cached
        if kind == "delta" and cached < MISS_RATIO * inp:
            g["misses"] += 1
            g["miss_uncached"] += inp - cached

    report = []
    for (model, kind), g in groups.items():
        report.append(
            {
                "model": model,
                "kind": kind,
                "calls": g["calls"],
                "input_tokens": g["input"],
                "cached_ratio": g["cached"] / g["input"] if g["input"] else 0.0,
                "uncached_tokens": g["input"] - g["cached"],
                "misses": g["misses"],
                "miss_uncached_tokens": g["miss_uncached"],
            }
        )
    report.sort(key=lambda r: r["uncached_tokens"], reverse=True)
    return report


def reset_report(db_path: str, since: Optional[datetime]) -> List[Dict[str, Any]]:
    """Action-selection requests by kind, and full requests by why their
    session history started anew (the router's labels in each call's
    metadata). Calls captured before the labels count as ``(unlabeled)``.

    Kinds: ``full`` (a history's first request: the whole prompt),
    ``delta`` (new events), ``correction`` (a retry's feedback on a reply the
    history holds), ``stateless`` (a provider without session histories).
    """
    groups: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "input": 0, "cached": 0}
    )
    for row in _decision_rows(db_path, since, "metadata, input_tokens, cached_tokens"):
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except ValueError:
            meta = {}
        request = meta.get("request", "(unlabeled)")
        reason = meta.get("reason", "")
        if meta.get("feedback"):
            reason += " (with feedback)"
        g = groups[(request, reason)]
        g["calls"] += 1
        g["input"] += row["input_tokens"]
        g["cached"] += row["cached_tokens"] or 0

    report = [
        {
            "request": request,
            "reason": reason,
            "calls": g["calls"],
            "input_tokens": g["input"],
            "uncached_tokens": g["input"] - g["cached"],
        }
        for (request, reason), g in groups.items()
    ]
    report.sort(key=lambda r: r["uncached_tokens"], reverse=True)
    return report


def _long_string_values(response: str) -> List[str]:
    """Long string parameter values of a decision reply (one per action)."""
    try:
        decision = json.loads(response)
    except (TypeError, ValueError):
        return []
    if not isinstance(decision, dict):
        return []
    actions = decision.get("actions")
    if not isinstance(actions, list):
        actions = [decision]
    values = []
    for action in actions:
        params = action.get("parameters") if isinstance(action, dict) else None
        if not isinstance(params, dict):
            continue
        for value in params.values():
            if isinstance(value, str) and len(value) >= LONG_PARAM_CHARS:
                values.append(value)
                break
    return values


def duplication_report(db_path: str, since: Optional[datetime]) -> Dict[str, Any]:
    """How often a long parameter value of a decision comes back in the same
    session's next request when that request is a delta."""
    checked = resent = 0
    previous: Optional[sqlite3.Row] = None
    # Full prompts are never checked, so their (large) text is not loaded.
    full = f"instr(user_prompt, '{FULL_PROMPT_MARK}') > 0"
    columns = (
        f"task_id, response, CASE WHEN {full} THEN '' ELSE user_prompt END "
        f"AS user_prompt, {full} AS full_prompt"
    )
    rows = _decision_rows(
        db_path, since, columns, "AND task_id IS NOT NULL", order="task_id, timestamp"
    )
    for row in rows:
        if (
            previous is not None
            and previous["task_id"] == row["task_id"]
            and not row["full_prompt"]
        ):
            for value in _long_string_values(previous["response"]):
                probe = value[:_PROBE_CHARS]
                checked += 1
                if (
                    probe in row["user_prompt"]
                    or json.dumps(probe)[1:-1] in row["user_prompt"]
                ):
                    resent += 1
        previous = row
    return {
        "long_values_checked": checked,
        "resent_in_next_delta": resent,
        "resent_ratio": resent / checked if checked else 0.0,
    }


def _print_sections(report: List[Dict[str, Any]]) -> None:
    if not report:
        print("No full action-selection prompts captured in this window.")
        return
    for layout in report:
        print(
            f"\n[{layout['layout']}] {layout['rows']} prompts, avg "
            f"{layout['avg_total_tokens']} tokens "
            f"({layout['avg_system_tokens']} in the system prompt)"
        )
        for b in layout["blocks"]:
            print(
                f"  {b['part']:6s}  {b['block']:28s} {b['avg_tokens']:>8d}  "
                f"{b['share'] * 100:5.1f}%"
            )


def _print_cache(report: List[Dict[str, Any]]) -> None:
    if not report:
        print("No action-selection calls captured in this window.")
        return
    print(
        f"{'MODEL':40s} {'KIND':5s} {'CALLS':>6s} {'INPUT':>13s} {'CACHED%':>8s} "
        f"{'UNCACHED':>12s} {'MISSES':>6s} {'MISS_UNCACHED':>13s}"
    )
    for r in report:
        print(
            f"{r['model'][:40]:40s} {r['kind']:5s} {r['calls']:6d} "
            f"{r['input_tokens']:13,d} {r['cached_ratio'] * 100:7.0f}% "
            f"{r['uncached_tokens']:12,d} {r['misses']:6d} "
            f"{r['miss_uncached_tokens']:13,d}"
        )


def _print_resets(report: List[Dict[str, Any]]) -> None:
    if not report:
        print("No action-selection calls captured in this window.")
        return
    print(
        f"{'REQUEST':12s} {'REASON':28s} {'CALLS':>6s} {'INPUT':>13s} {'UNCACHED':>12s}"
    )
    for r in report:
        print(
            f"{r['request']:12s} {r['reason'][:28]:28s} {r['calls']:6d} "
            f"{r['input_tokens']:13,d} {r['uncached_tokens']:12,d}"
        )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description="Profile prompt cache/latency/tokens.")
    ap.add_argument("--db", help="Path to llm_calls.db (default: app data dir).")
    ap.add_argument("--since", help="Only calls newer than e.g. 24h, 7d, 90m.")
    ap.add_argument("--json", metavar="PATH", help="Write the report as JSON.")
    ap.add_argument("--md", metavar="PATH", help="Write the report as markdown.")
    view = ap.add_mutually_exclusive_group()
    view.add_argument(
        "--sections",
        action="store_true",
        help="Tokens per action-selection prompt block.",
    )
    view.add_argument(
        "--cache", action="store_true", help="Action-selection cache use per model."
    )
    view.add_argument(
        "--duplication",
        action="store_true",
        help="Decision inputs sent again in the next delta.",
    )
    view.add_argument(
        "--resets",
        action="store_true",
        help="Action-selection requests by kind, full ones by why.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=50,
        help="--sections: how many of the latest full prompts to measure.",
    )
    args = ap.parse_args()

    db_path = args.db or _default_db_path()
    since = _parse_since(args.since)

    if args.sections or args.cache or args.duplication or args.resets:
        if args.sections:
            report: Any = section_report(db_path, since, args.limit)
            _print_sections(report)
        elif args.cache:
            report = cache_report(db_path, since)
            _print_cache(report)
        elif args.resets:
            report = reset_report(db_path, since)
            _print_resets(report)
        else:
            report = duplication_report(db_path, since)
            print(
                f"{report['resent_in_next_delta']} of {report['long_values_checked']} "
                f"long parameter values came back in the next delta "
                f"({report['resent_ratio'] * 100:.0f}%)."
            )
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
            print(f"\nWrote {args.json}")
        return 0

    rows = load_rows(db_path, since)

    if not rows:
        print(
            f"No captured LLM calls found in {db_path}"
            + (f" since {args.since}" if args.since else "")
        )
        print("Run the agent (with capture on) to populate llm_calls, then retry.")
        return 0

    agg = aggregate(rows)
    totals = _totals(agg)

    print(_fmt_table(agg))
    print("-" * 40)
    print(
        f"{totals['calls']} calls / {totals['groups']} groups   "
        f"{totals['total_input_tokens']} in / "
        f"{totals['total_output_tokens']} out tokens"
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"totals": totals, "prompts": agg}, fh, indent=2)
        print(f"\nWrote {args.json}")
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(_markdown(agg, totals))
        print(f"Wrote {args.md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
