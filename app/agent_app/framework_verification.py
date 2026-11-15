"""Parent-linked verification using CraftBot's existing subagent runtime."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from app.agent_app.framework_commands import skill_sources
from app.subagent.definitions.framework_walk_verify import (
    BLOCKED,
    DEFECTS,
    INCOMPLETE,
    PASS,
)


@dataclass
class VerificationTarget:
    path: str
    stamp: dict
    dev: dict
    host: object
    active: bool = True

    def check(self):
        if not self.active or self.host.gate_stamp(self.path) != self.stamp:
            raise PermissionError(
                "The verification candidate changed. Revalidate before verifying again."
            )
        if read_dev(self.path) != self.dev:
            raise PermissionError(
                "The assigned dev instance changed or stopped. Do not test the live app."
            )


verification_target: ContextVar[VerificationTarget | None] = ContextVar(
    "framework_verification_target", default=None
)


def read_dev(path):
    try:
        value = json.loads(
            (Path(path) / ".a2app" / "dev.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        value = None
    if not isinstance(value, dict) or not value.get("url"):
        raise ValueError(
            "Start and validate the dev instance before independent verification."
        )
    return value


def _git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    ).stdout


def verified_commit(path):
    """The commit a walk of the app at ``path`` verifies: HEAD of the app's own
    repository when no tracked file has changed. None when the app has no
    repository of its own or carries uncommitted work."""
    try:
        top = _git(path, "rev-parse", "--show-toplevel").strip()
        head = _git(path, "rev-parse", "HEAD").strip()
        changed = _git(path, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        return None
    if changed.strip() or Path(top).resolve() != Path(path).resolve():
        return None
    return head or None


def baseline(host, path):
    """What a walk of the app at ``path`` re-verifies from: the last finished
    walk (pass or defects) of a commit, or else the baseline that walk started
    from. Kept apart from the verification record, which the builder reads."""
    key = str(Path(path).resolve())
    previous = host.verification(path) or {}
    if previous.get("verdict") in (PASS, DEFECTS) and previous.get("commit"):
        return {name: previous[name] for name in ("verdict", "commit", "evidence")}
    return host.store.get("verification_baseline", key)


async def run_verification(host, row, stamp, request, parent_session_id):
    from app.internal_action_interface import InternalActionInterface as I
    from app.logger import logger, add_subagent_log_sink, remove_subagent_log_sink
    from app.subagent import SubAgentRunner

    parts = (
        I.subagent_manager,
        I.action_manager,
        I.action_library,
        I.event_stream_manager,
        I.llm_interface,
    )
    if any(part is None for part in parts):
        raise RuntimeError(
            "CraftBot's subagent runtime is unavailable; verification was not started."
        )
    manager, actions, library, events, llm = parts
    parent = host.agent.session_manager.get(parent_session_id)
    if parent is None or getattr(parent, "isolated_app_task", False):
        raise ValueError("Verification needs an existing owner conversation.")
    target = VerificationTarget(row["path"], stamp, read_dev(row["path"]), host)
    # Kept before this walk's own record replaces the last one.
    base = baseline(host, row["path"])
    if base:
        host.store.put("verification_baseline", str(Path(row["path"]).resolve()), base)
    commit = await asyncio.to_thread(verified_commit, row["path"])
    sources = await skill_sources()
    source = sources["framework-walk-verify"]
    skill = await asyncio.to_thread(source.read_text, encoding="utf-8")
    target.check()
    last = (
        f"Last verification: {base['verdict']} at commit {base['commit']}. "
        f"Its report:\n{base['evidence']}\n\n"
        if base
        else "Last verification: none.\n\n"
    )
    query = (
        f"Independently verify {row['name']} ({row['id']}).\n"
        f"App directory: {row['path']}\nDEV URL: {target.dev['url']}\n"
        f"Requirements: {Path(row['path']) / 'reference' / 'requirements.md'}\n"
        f"Evidence directory: {parent.workspace_dir or 'use the Mini Browser screenshot paths'}\n"
        f"Requested checks (builder claims, verify independently): {request}\n"
        f"{last}"
        f"Installed skill source: {source}\nResolve relative references from: {source.parent}\n"
        f"--- BEGIN UNCHANGED FRAMEWORK SKILL ---\n{skill}\n--- END FRAMEWORK SKILL ---"
    )
    sub = manager.spawn(
        "framework_walk_verify",
        query,
        parent_task_id=parent.id,
        parent_temp_dir=parent.workspace_dir,
    )
    assignment = {
        "path": row["path"],
        "appId": row["id"],
        "stamp": stamp,
        "commit": commit,
        "builderSessionId": parent.id,
        "mode": "subagent",
        "status": "running",
    }
    token = verification_target.set(target)
    agent_tag = f"sub:{sub.agent_type}:{sub.id.removeprefix('sub_')}"
    sink = None

    def record(verdict, evidence):
        report = host.report_verification(sub.id, verdict, evidence)
        report["status"] = sub.status
        host.store.put("verification", str(Path(row["path"]).resolve()), report)
        return report

    try:
        host.store.put("verification_session", sub.id, assignment)
        # Starting a new walk invalidates any earlier pass, including on cancellation.
        host.report_verification(
            sub.id, INCOMPLETE, "Independent verification is running."
        )
        await host.changed()
        runner = SubAgentRunner(manager, actions, library, events, llm)
        sink = add_subagent_log_sink(agent_tag, parent.id)
        with logger.contextualize(agent=agent_tag, session=parent.id):
            await runner.run_to_completion(sub)
        try:
            result = json.loads(sub.result or "")
            verdict, evidence = result["verdict"], result["evidence"]
            if verdict == PASS and sub.status != "completed":
                verdict = INCOMPLETE
                evidence = (
                    f"Verifier ended as {sub.status}; no pass recorded.\n{evidence}"
                )
            target.check()
            report = record(verdict, evidence)
        except (ValueError, TypeError, KeyError, PermissionError) as error:
            report = record(
                INCOMPLETE,
                f"Verification did not produce a valid result for this candidate: {error}\n{sub.result or sub.status}",
            )
        return {
            "sessionId": parent.id,
            "childTaskId": sub.id,
            "verification": report,
            "childStatus": sub.status,
            "iterations": sub.iterations,
        }
    except asyncio.CancelledError:
        sub.terminate("failed", "Verification canceled with its parent run.")
        record(INCOMPLETE, sub.result)
        raise
    except Exception as error:
        sub.terminate("error", str(error))
        report = record(BLOCKED, f"Verifier could not finish: {error}")
        return {
            "sessionId": parent.id,
            "childTaskId": sub.id,
            "verification": report,
            "childStatus": sub.status,
        }
    finally:
        target.active = False
        verification_target.reset(token)
        if sink is not None:
            remove_subagent_log_sink(sink)
        # Also covers setup failures before the runner enters its own finally.
        if events.has_stream(sub.id):
            try:
                manager.release(sub.id)
            except Exception as error:
                logger.warning(f"Verifier cleanup failed for {sub.id}: {error}")
        host.store.put(
            "verification_session", sub.id, {**assignment, "status": sub.status}
        )
        if not host.closing:
            await host.changed()
