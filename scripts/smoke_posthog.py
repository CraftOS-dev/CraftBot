#!/usr/bin/env python
"""Live smoke test for the PostHog integration — the gate the offline checks can't cover.

Drives the real PostHog client against a real account and prints one line per
operation. Read-only by default. `--write` additionally creates a dashboard, an
annotation and a feature flag, then deletes them again.

    python scripts/smoke_posthog.py --api-key phx_xxx
    python scripts/smoke_posthog.py --api-key phx_xxx --host eu
    python scripts/smoke_posthog.py --api-key phx_xxx --write

The key needs read scopes for: query, insight, dashboard, feature flag, cohort,
person, annotation, event definition, project, organization. `--write` also
needs write on dashboard, annotation and feature flag.

Exit code is 0 when every check passed or was skipped, 1 if any failed.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Windows consoles default to cp1252 and raise UnicodeEncodeError on the
# arrows and dashes in provider messages. Force UTF-8 where we can.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
    pass


def _reexec_on_craftbot_interpreter() -> None:
    """Re-run under the interpreter that has CraftBot's dependencies.

    The user's `python` is usually a trampoline without httpx installed, so
    these scripts would fail on import. app/python_runtime.py resolves the
    real one; mirror what the launchers do rather than making the caller
    remember a path.
    """
    import os

    if os.environ.get("_CRAFTBOT_REEXEC") == "1":
        return
    try:
        from app.python_runtime import resolve
    except Exception:  # pragma: no cover - fall through to a normal import error
        return
    target = resolve()
    if not target or Path(target).resolve() == Path(sys.executable).resolve():
        return
    os.environ["_CRAFTBOT_REEXEC"] = "1"
    raise SystemExit(
        subprocess.call([target, str(Path(__file__).resolve()), *sys.argv[1:]])
    )


_reexec_on_craftbot_interpreter()

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


class Results:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        icon = {PASS: "  ok  ", FAIL: " FAIL ", SKIP: " skip "}[status]
        print(f"{icon} {name:42s} {detail}"[:160], flush=True)
        self.rows.append((status, name, detail))

    @property
    def failed(self) -> List[Tuple[str, str, str]]:
        return [r for r in self.rows if r[0] == FAIL]


def summarize(raw: Any) -> str:
    """One-line description of what came back."""
    if not isinstance(raw, dict):
        return str(raw)[:80]
    if "error" in raw:
        return f"{raw['error']} {str(raw.get('details') or '')[:90]}"
    result = raw.get("result")
    if isinstance(result, dict):
        if "results" in result and isinstance(result["results"], list):
            return f"{len(result['results'])} rows"
        if "count" in result:
            return f"count={result['count']}"
        if "id" in result:
            return f"id={result['id']}"
        return f"keys: {', '.join(list(result)[:5])}"
    if isinstance(result, list):
        return f"{len(result)} items"
    return str(result)[:80]


async def check(results: Results, name: str, coro) -> Optional[Dict[str, Any]]:
    """Await one client call and record whether the API accepted it."""
    try:
        raw = await coro
    except Exception as exc:  # noqa: BLE001 - surfacing any failure is the point
        results.add(FAIL, name, f"raised {type(exc).__name__}: {exc}")
        return None
    if isinstance(raw, dict) and "error" in raw:
        results.add(FAIL, name, summarize(raw))
        return None
    results.add(PASS, name, summarize(raw))
    return raw


def result_of(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not raw:
        return {}
    value = raw.get("result")
    return value if isinstance(value, dict) else {}


def first_id(raw: Optional[Dict[str, Any]]) -> Optional[str]:
    """Pull the first row's id out of a paginated list response."""
    payload = result_of(raw)
    rows = payload.get("results")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        value = rows[0].get("id")
        if value is not None:
            return str(value)
    return None


async def run(args: argparse.Namespace) -> int:
    from craftos_integrations import autoload_integrations, configure
    from craftos_integrations.providers.posthog import PostHogProvider

    configure(project_root=REPO_ROOT)
    autoload_integrations(force=True)

    provider = PostHogProvider()
    results = Results()

    print("\n--- connect ---")
    ok, message, credential = provider.verify_token(
        {
            "api_key": args.api_key,
            "host": args.host,
            "project_id": args.project_id or "",
        }
    )
    if not ok or credential is None:
        results.add(FAIL, "verify_token", message)
        print(f"\nCannot continue: {message}")
        return 1
    results.add(PASS, "verify_token", message)
    print(
        f"       host={credential['host']} org={credential['org_id']} "
        f"project={credential['project_id'] or '(none)'}"
    )

    client = provider.build_client(credential, lambda _: None)

    # ── read-only ────────────────────────────────────────────────────
    print("\n--- read-only ---")
    await check(results, "get_current_user", client.get_current_user())
    await check(results, "get_organization", client.get_organization())
    await check(
        results, "list_organization_members", client.list_organization_members()
    )
    await check(results, "list_projects", client.list_projects())
    await check(results, "get_project", client.get_project())

    print("\n--- query (the one that matters most) ---")
    top_events = await check(
        results,
        "run_query (HogQL)",
        client.run_query(
            "SELECT event, count() AS n FROM events "
            "WHERE timestamp > now() - interval 7 day "
            "GROUP BY event ORDER BY n DESC LIMIT 10"
        ),
    )
    rows = result_of(top_events).get("results")
    if isinstance(rows, list) and rows:
        print(f"       top events: {', '.join(str(r[0]) for r in rows[:5])}")
    elif top_events is not None:
        print("       (no events in the last 7 days — query worked, project is quiet)")

    started = await check(
        results,
        "run_query_async",
        client.run_query_async("SELECT count() FROM events"),
    )
    query_id = (result_of(started).get("query_status") or {}).get("id")
    if query_id:
        await asyncio.sleep(1.0)
        await check(results, "get_query_status", client.get_query_status(str(query_id)))
    else:
        results.add(SKIP, "get_query_status", "no query id returned")

    await check(results, "list_events", client.list_events(limit=5))

    print("\n--- resources ---")
    insights = await check(results, "list_insights", client.list_insights(limit=5))
    insight_id = first_id(insights)
    if insight_id:
        await check(results, "get_insight", client.get_insight(insight_id))
    else:
        results.add(SKIP, "get_insight", "no insights in this project")

    dashboards = await check(
        results, "list_dashboards", client.list_dashboards(limit=5)
    )
    dashboard_id = first_id(dashboards)
    if dashboard_id:
        await check(results, "get_dashboard", client.get_dashboard(dashboard_id))
    else:
        results.add(SKIP, "get_dashboard", "no dashboards in this project")

    flags = await check(
        results, "list_feature_flags", client.list_feature_flags(limit=5)
    )
    flag_id = first_id(flags)
    if flag_id:
        await check(results, "get_feature_flag", client.get_feature_flag(flag_id))
        await check(
            results, "get_feature_flag_status", client.get_feature_flag_status(flag_id)
        )
    else:
        results.add(SKIP, "get_feature_flag", "no feature flags in this project")

    await check(results, "list_persons", client.list_persons(limit=5))
    await check(results, "list_cohorts", client.list_cohorts(limit=5))
    await check(results, "list_annotations", client.list_annotations(limit=5))
    await check(
        results, "list_event_definitions", client.list_event_definitions(limit=5)
    )
    await check(
        results, "list_property_definitions", client.list_property_definitions(limit=5)
    )
    await check(results, "list_actions", client.list_actions(limit=5))
    await check(
        results, "list_dashboard_templates", client.list_dashboard_templates(limit=5)
    )

    # ── write ────────────────────────────────────────────────────────
    if not args.write:
        print("\n--- write: skipped (pass --write to test creates and deletes) ---")
    else:
        stamp = time.strftime("%H%M%S")
        print("\n--- write (creates then deletes) ---")

        created = await check(
            results,
            "create_dashboard",
            client.create_dashboard(
                name=f"CraftBot smoke test {stamp}",
                description="Created by scripts/smoke_posthog.py — safe to delete.",
            ),
        )
        new_dashboard = result_of(created).get("id")
        if new_dashboard:
            await check(
                results,
                "update_dashboard",
                client.update_dashboard(str(new_dashboard), description="renamed"),
            )
            await check(
                results,
                "create_dashboard_text_tile",
                client.create_dashboard_text_tile(
                    str(new_dashboard), "## smoke test tile"
                ),
            )
            await check(
                results,
                "delete_dashboard (soft)",
                client.delete_dashboard(str(new_dashboard)),
            )
        else:
            for name in (
                "update_dashboard",
                "create_dashboard_text_tile",
                "delete_dashboard (soft)",
            ):
                results.add(SKIP, name, "dashboard was not created")

        annotation = await check(
            results,
            "create_annotation",
            client.create_annotation(content=f"CraftBot smoke test {stamp}"),
        )
        new_annotation = result_of(annotation).get("id")
        if new_annotation:
            await check(
                results,
                "delete_annotation (soft)",
                client.delete_annotation(str(new_annotation)),
            )
        else:
            results.add(SKIP, "delete_annotation (soft)", "annotation was not created")

        flag = await check(
            results,
            "create_feature_flag",
            client.create_feature_flag(
                key=f"craftbot-smoke-test-{stamp}",
                name="CraftBot smoke test",
                active=False,
                rollout_percentage=0,
            ),
        )
        new_flag = result_of(flag).get("id")
        if new_flag:
            await check(
                results,
                "set_feature_flag_rollout",
                client.set_feature_flag_rollout(str(new_flag), 25),
            )
            await check(
                results,
                "enable_feature_flag",
                client.enable_feature_flag(str(new_flag)),
            )
            await check(
                results,
                "disable_feature_flag",
                client.disable_feature_flag(str(new_flag)),
            )
            await check(
                results,
                "delete_feature_flag (soft)",
                client.delete_feature_flag(str(new_flag)),
            )
        else:
            for name in (
                "set_feature_flag_rollout",
                "enable_feature_flag",
                "disable_feature_flag",
                "delete_feature_flag (soft)",
            ):
                results.add(SKIP, name, "flag was not created")

    # ── summary ──────────────────────────────────────────────────────
    passed = sum(1 for r in results.rows if r[0] == PASS)
    skipped = sum(1 for r in results.rows if r[0] == SKIP)
    print("\n" + "=" * 68)
    print(f"{passed} passed, {len(results.failed)} failed, {skipped} skipped")

    if results.failed:
        print("\nFailures:")
        for _, name, detail in results.failed:
            print(f"  - {name}: {detail}")
        print(
            "\nA 403 means the personal API key lacks that scope — mint a new key "
            "with it; scopes can't be added to an existing key."
        )
        return 1

    print("\nEvery call the API was asked to accept, it accepted.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--api-key", required=True, help="PostHog personal API key (phx_…)"
    )
    parser.add_argument(
        "--host", default="us", help="'us', 'eu', or a self-hosted URL (default: us)"
    )
    parser.add_argument(
        "--project-id", default="", help="override the detected project"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="also create and delete a dashboard, annotation and feature flag",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
