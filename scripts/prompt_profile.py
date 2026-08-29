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

Usage:
    python scripts/prompt_profile.py                       # all captured calls
    python scripts/prompt_profile.py --since 24h           # last 24 hours
    python scripts/prompt_profile.py --md report.md --json report.json
    python scripts/prompt_profile.py --db path/to/llm_calls.db
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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
    args = ap.parse_args()

    db_path = args.db or _default_db_path()
    since = _parse_since(args.since)
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
