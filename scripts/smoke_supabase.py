#!/usr/bin/env python
"""Live smoke test for the Supabase integration — the gate the offline checks can't cover.

Drives the real Supabase client against a real account and prints one line per
operation. Read-only by default. `--write` additionally exercises every write
path on throwaway resources in ONE project, then removes them again:

  migration (create table) → insert / select / update / delete rows → RPC-free
  SQL write → bucket + upload / download / sign / move / delete → auth user
  create / update / delete → secret set / delete → edge function deploy /
  invoke / delete → a reversing migration that drops the table.

    python scripts/smoke_supabase.py --token sbp_xxx
    python scripts/smoke_supabase.py --token sbp_xxx --project-ref abcdefghijklmnopqrst
    python scripts/smoke_supabase.py --token sbp_xxx --project-ref abcd... --write

Use a scratch project for --write. Nothing here creates, pauses or deletes a
project. Every throwaway resource is named craftbot_smoke_<timestamp>.

Exit code is 0 when every check passed or was skipped, 1 if any failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
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
    """Re-run under the interpreter that has CraftBot's dependencies."""
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
    if not isinstance(raw, dict):
        return str(raw)[:80]
    if "error" in raw:
        return f"{raw['error']} {str(raw.get('details') or '')[:90]}"
    result = raw.get("result")
    if isinstance(result, dict):
        for key in ("rows", "users", "lints"):
            if isinstance(result.get(key), list):
                return f"{len(result[key])} {key}"
        return f"keys: {', '.join(list(result)[:5])}"
    if isinstance(result, list):
        return f"{len(result)} items"
    return str(result)[:80]


async def check(results: Results, name: str, coro) -> Optional[Dict[str, Any]]:
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


def result_of(raw: Optional[Dict[str, Any]]) -> Any:
    return (raw or {}).get("result")


async def run(args: argparse.Namespace) -> int:
    from craftos_integrations import autoload_integrations, configure
    from craftos_integrations.providers.supabase import SupabaseProvider

    configure(project_root=REPO_ROOT)
    autoload_integrations(force=True)

    provider = SupabaseProvider()
    results = Results()

    print("\n--- connect ---")
    if args.connected:
        # The account the user connected in Settings — the token never
        # appears on the command line or in shell history.
        from craftos_integrations.core.storage import FileCredentialStore
        from craftos_integrations.core.system import IntegrationSystem
        from craftos_integrations.providers import default_providers

        system = IntegrationSystem(
            store=FileCredentialStore(), providers=default_providers()
        )
        accounts = system.list_accounts("supabase")
        if not accounts:
            print("\nNo Supabase account connected in CraftBot.")
            return 1
        client = system.client_for("supabase", accounts[0].identity)
        results.add(PASS, "connected account", accounts[0].identity)
        ok, message, _ = provider.verify_token(
            {"access_token": client._load().access_token}
        )
        results.add(PASS if ok else FAIL, "verify_token", message)
    else:
        if not args.token:
            print("Pass --token or --connected.")
            return 1
        ok, message, credential = provider.verify_token({"access_token": args.token})
        if not ok or credential is None:
            results.add(FAIL, "verify_token", message)
            print(f"\nCannot continue: {message}")
            return 1
        results.add(PASS, "verify_token", message)
        print(f"       identity={provider.identity_of(credential)}")
        client = provider.build_client(credential, lambda _: None)

    # ── account level ────────────────────────────────────────────────
    print("\n--- account ---")
    orgs = await check(results, "list_organizations", client.list_organizations())
    projects = await check(results, "list_projects", client.list_projects())
    # Some tokens list no organizations even though their projects belong
    # to one — fall back to the projects' organization.
    slugs = [o.get("slug") for o in (result_of(orgs) or [])] or [
        p.get("organization_slug") for p in (result_of(projects) or [])
    ]
    if slugs and slugs[0]:
        await check(results, "list_organization_members",
                    client.list_organization_members(slugs[0]))
        await check(results, "list_regions", client.list_regions(slugs[0]))
    else:
        results.add(SKIP, "list_organization_members", "no organization visible")

    ref = args.project_ref
    if not ref:
        active = [
            p for p in (result_of(projects) or [])
            if str(p.get("status", "")).startswith("ACTIVE")
        ]
        ref = active[0]["ref"] if active else ""
    if not ref:
        print("\nNo active project to test against — pass --project-ref.")
        return 1 if results.failed else 0
    print(f"       project={ref}")

    # ── project reads ────────────────────────────────────────────────
    print("\n--- project reads ---")
    await check(results, "get_project", client.get_project(ref))
    await check(results, "get_project_health", client.get_project_health(project_ref=ref))
    await check(results, "get_project_keys", client.get_project_keys(ref))
    for service in ("auth", "postgrest", "realtime", "storage", "postgres"):
        await check(
            results, f"get_service_config[{service}]",
            client.get_service_config(service, project_ref=ref),
        )
    await check(results, "run_sql_readonly", client.run_sql_readonly(
        "select $1::text as echo, now() as at", parameters=["hi"], project_ref=ref))
    tables = await check(results, "list_tables", client.list_tables(project_ref=ref))
    table_rows = result_of(tables) or []
    if table_rows:
        first = table_rows[0]
        await check(results, "describe_table", client.describe_table(
            first["name"], schema=first["schema"], project_ref=ref))
    else:
        results.add(SKIP, "describe_table", "no tables in public")
    await check(results, "list_extensions", client.list_extensions(project_ref=ref))
    await check(results, "generate_typescript_types",
                client.generate_typescript_types(project_ref=ref))
    await check(results, "list_backups", client.list_backups(project_ref=ref))
    await check(results, "list_migrations", client.list_migrations(project_ref=ref))
    await check(results, "list_buckets", client.list_buckets(project_ref=ref))
    await check(results, "list_users", client.list_users(per_page=5, project_ref=ref))
    await check(results, "list_functions", client.list_functions(project_ref=ref))
    await check(results, "list_secrets", client.list_secrets(project_ref=ref))
    await check(results, "list_branches", client.list_branches(project_ref=ref))
    for source in ("api", "postgres", "auth"):
        await check(results, f"get_logs[{source}]",
                    client.get_logs(source=source, limit=5, project_ref=ref))
    await check(results, "get_security_advisors", client.get_security_advisors(project_ref=ref))
    await check(results, "get_performance_advisors",
                client.get_performance_advisors(project_ref=ref))
    await check(results, "get_api_usage", client.get_api_usage(project_ref=ref))

    if args.write:
        await run_writes(client, ref, results)

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
            "\nBranch calls 4xx on projects without branching (paid plans) — "
            "expected there. A 403 elsewhere means the account's org role is "
            "read-only."
        )
        return 1
    print("\nEvery call the API was asked to accept, it accepted.")
    return 0


async def run_writes(client: Any, ref: str, results: Results) -> None:
    stamp = time.strftime("%Y%m%d%H%M%S")
    name = f"craftbot_smoke_{stamp}"

    # ── migrations + rows ────────────────────────────────────────────
    print("\n--- write: schema + rows ---")
    migration = await check(results, "apply_migration", client.apply_migration(
        f"create table public.{name} (id bigint generated always as identity "
        f"primary key, label text not null, n int default 0);",
        name=f"create_{name}",
        rollback=f"drop table if exists public.{name};",
        project_ref=ref,
    ))
    if migration is not None:
        await check(results, "insert_rows", client.insert_rows(
            name, [{"label": "a"}, {"label": "b"}], project_ref=ref))
        await check(results, "select_rows", client.select_rows(
            name, order="id.asc", count=True, project_ref=ref))
        await check(results, "update_rows", client.update_rows(
            name, {"n": 5}, {"label": "eq.a"}, project_ref=ref))
        await check(results, "delete_rows", client.delete_rows(
            name, {"label": "eq.b"}, project_ref=ref))
        await check(results, "run_sql (write)", client.run_sql(
            f"insert into public.{name} (label) values ($1) returning id",
            parameters=["c"], project_ref=ref))
    else:
        for step in ("insert_rows", "select_rows", "update_rows", "delete_rows",
                     "run_sql (write)"):
            results.add(SKIP, step, "table was not created")

    # ── storage ──────────────────────────────────────────────────────
    print("\n--- write: storage ---")
    bucket = name.replace("_", "-")
    made = await check(results, "create_bucket", client.create_bucket(bucket, project_ref=ref))
    if made is not None:
        await check(results, "update_bucket", client.update_bucket(
            bucket, file_size_limit=1048576, project_ref=ref))
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "hello.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write("hello from craftbot")
            await check(results, "upload_file", client.upload_file(
                bucket, "dir/hello.txt", src, project_ref=ref))
            await check(results, "list_files", client.list_files(
                bucket, prefix="dir", project_ref=ref))
            dst = os.path.join(tmp, "back.txt")
            got = await check(results, "download_file", client.download_file(
                bucket, "dir/hello.txt", dst, project_ref=ref))
            if got is not None:
                with open(dst, encoding="utf-8") as f:
                    same = f.read() == "hello from craftbot"
                results.add(PASS if same else FAIL, "download round-trip",
                            "content matches" if same else "content differs")
        await check(results, "create_signed_url", client.create_signed_url(
            bucket, "dir/hello.txt", expires_in=60, project_ref=ref))
        await check(results, "copy_file", client.copy_file(
            bucket, "dir/hello.txt", "dir/copy.txt", project_ref=ref))
        await check(results, "move_file", client.move_file(
            bucket, "dir/copy.txt", "dir/moved.txt", project_ref=ref))
        await check(results, "delete_files", client.delete_files(
            bucket, ["dir/moved.txt"], project_ref=ref))
        await check(results, "empty_bucket", client.empty_bucket(bucket, project_ref=ref))
        await check(results, "delete_bucket", client.delete_bucket(bucket, project_ref=ref))

    # ── auth users ───────────────────────────────────────────────────
    print("\n--- write: auth users ---")
    user = await check(results, "create_user", client.create_user(
        email=f"{name}@example.com", password=f"Smoke-{stamp}-pw!",
        email_confirm=True, project_ref=ref))
    user_id = (result_of(user) or {}).get("id") if user else None
    if user_id:
        await check(results, "get_user", client.get_user(user_id, project_ref=ref))
        await check(results, "update_user", client.update_user(
            user_id, user_metadata={"smoke": True}, project_ref=ref))
        await check(results, "generate_auth_link", client.generate_auth_link(
            "magiclink", f"{name}@example.com", project_ref=ref))
        await check(results, "delete_user", client.delete_user(user_id, project_ref=ref))
    else:
        for step in ("get_user", "update_user", "generate_auth_link", "delete_user"):
            results.add(SKIP, step, "user was not created")

    # ── secrets + edge function ──────────────────────────────────────
    print("\n--- write: secrets + edge function ---")
    secret = f"CRAFTBOT_SMOKE_{stamp}"
    await check(results, "set_secrets", client.set_secrets({secret: "ok"}, project_ref=ref))
    slug = f"craftbot-smoke-{stamp}"
    deployed = await check(results, "deploy_function", client.deploy_function(
        slug,
        files={"index.ts": (
            "Deno.serve(async (req) => new Response(JSON.stringify({ "
            f"secret: Deno.env.get('{secret}') }}), "
            "{ headers: { 'Content-Type': 'application/json' } }))"
        )},
        verify_jwt=False,
        project_ref=ref,
    ))
    if deployed is not None:
        await check(results, "get_function", client.get_function(slug, project_ref=ref))
        await check(results, "update_function", client.update_function(
            slug, name="CraftBot smoke", project_ref=ref))
        # Freshly deployed functions can take a few seconds to route.
        await asyncio.sleep(5)
        await check(results, "invoke_function", client.invoke_function(
            slug, body={}, project_ref=ref))
        await check(results, "delete_function", client.delete_function(slug, project_ref=ref))
    await check(results, "delete_secrets", client.delete_secrets([secret], project_ref=ref))

    # ── cleanup: a reversing migration (rollback is branch-only) ─────
    print("\n--- write: cleanup ---")
    if migration is not None:
        await check(results, "apply_migration (drop)", client.apply_migration(
            f"drop table if exists public.{name};",
            name=f"drop_{name}",
            project_ref=ref,
        ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--token", default="", help="Supabase personal access token (sbp_…)")
    parser.add_argument(
        "--connected", action="store_true",
        help="use the Supabase account connected in CraftBot instead of --token",
    )
    parser.add_argument("--project-ref", default="", help="project to test (default: first active)")
    parser.add_argument(
        "--write",
        action="store_true",
        help="also exercise every write path on throwaway resources, then clean up",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
