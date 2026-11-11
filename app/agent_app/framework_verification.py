"""Parent-linked verification using CraftBot's existing subagent runtime."""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from app.agent_app.framework_commands import skill_sources


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
    sources = await skill_sources()
    source = sources["framework-walk-verify"]
    skill = await asyncio.to_thread(source.read_text, encoding="utf-8")
    target.check()
    query = (
        f"Independently verify {row['name']} ({row['id']}).\n"
        f"App directory: {row['path']}\nDEV URL: {target.dev['url']}\n"
        f"Requirements: {Path(row['path']) / 'reference' / 'requirements.md'}\n"
        f"Evidence directory: {parent.workspace_dir or 'use the Mini Browser screenshot paths'}\n"
        f"Requested checks (builder claims, verify independently): {request}\n\n"
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
            sub.id, "incomplete", "Independent verification is running."
        )
        await host.changed()
        runner = SubAgentRunner(manager, actions, library, events, llm)
        sink = add_subagent_log_sink(agent_tag, parent.id)
        with logger.contextualize(agent=agent_tag, session=parent.id):
            await runner.run_to_completion(sub)
        try:
            result = json.loads(sub.result or "")
            verdict, evidence = result["verdict"], result["evidence"]
            if verdict == "pass" and sub.status != "completed":
                verdict = "incomplete"
                evidence = (
                    f"Verifier ended as {sub.status}; no pass recorded.\n{evidence}"
                )
            target.check()
            report = record(verdict, evidence)
        except (ValueError, TypeError, KeyError, PermissionError) as error:
            report = record(
                "incomplete",
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
        record("incomplete", sub.result)
        raise
    except Exception as error:
        sub.terminate("error", str(error))
        report = record("blocked", f"Verifier could not finish: {error}")
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
