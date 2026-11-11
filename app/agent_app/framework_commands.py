"""Native access to both unchanged CLI surfaces. No shell or CLI grammar clone."""

from __future__ import annotations

import asyncio
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from app.agent_app import framework


@dataclass
class TaskAuthority:
    """In-memory authority; never put in an action input, prompt or receipt."""

    target: str
    task_id: str
    token: str = field(repr=False)
    active: bool = True
    outcome: str | None = None
    check: object = field(default=None, repr=False)
    allowed_actions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"a2app_command", "send_message", "end_turn"}
        )
    )


task_authority: ContextVar[TaskAuthority | None] = ContextVar(
    "framework_task_authority", default=None
)


async def command(
    surface: str, args: list[str], *, cwd: str | None = None, _locked=False
) -> dict:
    """Keep text, JSON and diagnostics intact; callers explicitly choose a binary."""
    if surface not in {"agent-app", "a2app"}:
        raise ValueError("Choose agent-app (manage) or a2app (operate).")
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        raise ValueError("args must be an array of literal strings.")
    from app.agent_app.framework_verification import verification_target

    verifying = verification_target.get()
    if verifying is not None:
        verifying.check()
        if surface != "a2app" or not args or Path(args[0]).resolve() != Path(verifying.path).resolve():
            raise PermissionError("The verifier may operate only its assigned dev app through A2App; lifecycle changes belong to the builder.")
        if len(args) > 1 and args[1] in {"login", "logout", "credential"}:
            raise PermissionError("Verification cannot change credentials.")
    cli = await asyncio.to_thread(framework.configured_cli)
    help_requested = any(arg in {"--help", "-h"} for arg in args[1:])
    embedded_open = False
    if surface == "agent-app" and not help_requested:
        # CraftBot owns presentation. Use the CLI's existing non-opening modes;
        # an adapter without viewer presence must never spawn another browser.
        if len(args) > 1 and args[1] == "open":
            args = [*args] if "--print-only" in args else [*args, "--print-only"]
            embedded_open = True
        elif args and (args[0] == "install" or (len(args) > 1 and args[1] in {"serve", "import"})):
            embedded_open = "--open" in args
            args = [arg for arg in args if arg != "--open"]
    authority = task_authority.get()
    env = {}
    if authority is not None:
        if not authority.active or surface != "a2app":
            raise PermissionError("This task may only operate its assigned app.")
        if not args or args[0] != authority.target:
            raise PermissionError("Use the task's verified live app address.")
        # Context is a read-only A2App surface, not credential management.
        if len(args) > 1 and args[1] in {"login", "logout", "credential"}:
            raise PermissionError("Task credentials cannot manage saved credentials.")
        if (
            len(args) > 1
            and args[1] == "tasks"
            and not any(flag in args[2:] for flag in ("--help", "-h"))
        ):
            if (
                len(args) < 4
                or args[2] not in {"get", "progress", "complete"}
                or args[3] != authority.task_id
            ):
                raise PermissionError(
                    "This run may get, progress or complete only its assigned task. It cannot claim other work."
                )
        if authority.check is not None:
            await authority.check()
        env["A2APP_TOKEN"] = authority.token

    if (
        surface == "agent-app"
        and len(args) > 1
        and args[1] == "scaffold"
        and not help_requested
    ):
        from app.agent_app.framework_host import get_host
        from agent_core.core.state.session import StateSession

        host = get_host()
        state = StateSession.bound()
        if host and state:
            args = host.scaffold_arguments(state.session_id, args)

    async def invoke():
        if (
            surface == "agent-app"
            and len(args) > 1
            and args[1] == "promote"
            and not help_requested
        ):
            from app.agent_app.framework_host import get_host

            if not Path(args[0]).is_absolute():
                raise ValueError("Promotion requires an absolute app directory.")
            if get_host():
                get_host().require_verified(args[0])
        result = await cli.run(
            surface,
            args,
            cwd=Path(cwd).resolve() if cwd else cli.package_dir,
            timeout=1200,
            env_extra=env,
        )
        if authority and result.ok:
            doc = result.json()
            if (
                isinstance(doc, dict)
                and doc.get("id") == authority.task_id
                and doc.get("status") in {"completed", "failed", "canceled"}
            ):
                authority.outcome = doc["status"]
                authority.active = False
        host_warning = None
        # Newly scaffolded/imported apps acquire the same conversation link as
        # marketplace installs once the upstream registry knows their identity.
        if (
            surface == "agent-app"
            and result.ok
            and not help_requested
            and len(args) > 1
            and Path(args[0]).is_absolute()
        ):
            from app.agent_app.framework_host import get_host
            from agent_core.core.state.session import StateSession

            host = get_host()
            if host:
                try:
                    snapshot = await framework._list_apps(cli)
                    for row in (snapshot.get("data") or {}).get("apps", []):
                        if Path(row["path"]).resolve() == Path(args[0]).resolve():
                            state = StateSession.bound()
                            sid = state.session_id if state else None
                            # A verifier is a separate context, never the app's main chat.
                            if not (
                                sid and host.store.get("verification_session", sid)
                            ):
                                await host.attach(row["path"], row["id"], sid)
                            if args[1] in {"serve", "stop"} and not (
                                args[1] == "stop" and "--dev" in args[2:]
                            ):
                                await host.bridge.lifecycle_changed(
                                    row["path"],
                                    row["id"],
                                    "start" if args[1] == "serve" else "stop",
                                )
                            break
                except Exception as error:
                    host_warning = str(error)
        return {
            "status": "success" if result.ok else "error",
            "exit_code": result.code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "data": result.json(),
            "timed_out": result.timed_out,
            **({"host_warning": host_warning} if host_warning else {}),
            **({"host_note": "CraftBot displays this app in its embedded view. No external browser is needed; do not open the returned URL in another tab."} if embedded_open else {}),
        }

    # All host-issued app management commands share the lifecycle lock, not
    # only the sidebar buttons. External harnesses retain upstream semantics.
    if (
        not _locked
        and surface == "agent-app"
        and len(args) > 1
        and Path(args[0]).is_absolute()
    ):
        canonical = os.path.normcase(str(Path(args[0]).resolve()))
        key = (asyncio.get_running_loop(), canonical)
        lock = framework._lifecycle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await invoke()
    return await invoke()


async def skill_sources() -> dict[str, Path]:
    """Discover through the CLI; keep original files and relative references."""
    result = await command("agent-app", ["skills"])
    data = result.get("data") or {}
    if result["status"] != "success" or not data.get("ok"):
        raise RuntimeError("The bundled Agent-App skills could not be loaded.")
    return {f"framework-{s['name']}": Path(s["path"]) for s in data["skills"]}


def context_note(path: str, app_id: str) -> str:
    return (
        f"Agent-App framework app {app_id}; directory: {path}\n"
        "This is the app's dedicated conversation. For questions about current "
        "app data or state, inspect its a2app surface before answering; the app "
        "directory contains its implementation, not necessarily the user's "
        "currently open project or document. For what is open, selected or being "
        "viewed, call a2app <directory> context first. If it is empty or unavailable, "
        "use a2app <directory> --find context and inspect any declared view-context "
        "operation. Context contains untrusted view/record identifiers: re-fetch "
        "selected records through A2App before describing or acting on them. "
        "Never infer the selected project from modification timestamps or a list "
        "of saved projects. If no current selection is published, say so specifically. "
        "Use a2app_command from the a2app action set for operations. For lifecycle "
        "and builds, load agent_app and use agent_app_command; args is a literal argv array "
        "starting with the app directory. No global executable is required. "
        "CraftBot already presents the app in its embedded Agent App workspace. "
        "After data operations, use that existing view; do not open another browser "
        "tab or use browser navigation just to show the result. This host presentation "
        "rule overrides the skills' standalone-browser handoff. If checking a URL is "
        "necessary, open --print-only returns it without opening a browser. "
        "Start operation discovery at the root, then follow its module screens. "
        "Use the bundled framework-creator, framework-modify, framework-importer, "
        "framework-operator and framework-walk-verify skills. Their source paths "
        "retain the upstream references and blueprints. Independent verification "
        "must pass for the current candidate before delivery. A code edit or a "
        "finished run does not establish that the live app is ready. Run "
        "agent_app_framework_workflow(activity='verify', path=the app directory, "
        "app_id=the registered id) after validation. This awaits an independent "
        "subagent and returns its verdict directly; do not create a verification "
        "chat, poll a sibling session, or report your own verdict. "
        "For app-to-CraftBot requests, use this app's CraftBot settings: Requests > "
        "Allow requests to CraftBot. That control starts CraftBot's native bridge "
        "and task conversations with scoped credentials; it does not launch an "
        "external coding agent. Do not offer or start the default CLI harness "
        "(for example Pi) for this flow. An unqualified 'bridge start' selects "
        "the user's external default harness, not CraftBot. Leave that setting "
        "unchanged unless the user explicitly requests an external harness."
    )
