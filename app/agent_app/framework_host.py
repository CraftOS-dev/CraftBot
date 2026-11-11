"""Native conversations and recoverable install jobs over the upstream CLI."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from agent_core.core.session import MAIN_SESSION_ID, SessionType

from app.agent_app import framework
from app.agent_app.framework_commands import command, context_note
from app.agent_app.framework_store import HostStore, app_key

_host = None


async def no_ui_change():
    """The framework host also runs without a browser client."""


def get_host():
    return _host


class FrameworkHost:
    def __init__(self, agent, changed=None, store=None):
        global _host
        self.agent = agent
        self.changed = changed or no_ui_change
        self.store = store or HostStore()
        self.jobs = {}
        self.verification_runs = {}
        self.restoring = None
        self.closing = False
        self.resetting = False
        from app.agent_app.framework_bridge import FrameworkBridge

        self.bridge = FrameworkBridge(self)
        from app.agent_app.framework_maintenance import FrameworkMaintenance
        from app.agent_app.framework_sharing import FrameworkSharing

        self.maintenance = FrameworkMaintenance(self)
        self.sharing = FrameworkSharing(self)
        _host = self
        for job in self.store.all("install"):
            if job["status"] == "running":
                job.update(
                    status="interrupted",
                    error="CraftBot restarted. Inspect the destination and registry before retrying; installation was not replayed.",
                )
                self.store.put("install", job["id"], job)

    async def selected(self, path, app_id, *, allow_missing=False):
        result = await framework.list_apps()
        if result["status"] != "success":
            raise RuntimeError(result["message"])
        row = next(
            (
                r
                for r in result["data"]["apps"]
                if r["path"] == path and r["id"] == app_id
            ),
            None,
        )
        if row is None or (row.get("status") == "missing" and not allow_missing):
            raise ValueError(
                "The selected app is no longer registered at this location."
            )
        return row

    async def reset_apps(self):
        """Apply the selected Agent Apps reset through the existing CLI flow."""
        if self.resetting:
            raise RuntimeError("Agent Apps reset is already running.")
        self.resetting = True
        deleted, failures = 0, []
        try:
            # A pending install must not register another app after the snapshot.
            jobs = [*self.jobs.values(), *self.verification_runs.values()]
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            pending = [
                session.id
                for session in list(self.agent.session_manager.sessions.values())
                if getattr(session, "agent_app_framework_pending", False)
            ]
            for sid in pending:
                await self.agent.request_run_stop(sid)
            snapshot = await framework.list_apps()
            if snapshot["status"] != "success":
                raise RuntimeError(snapshot["message"])
            cli = await asyncio.to_thread(framework.configured_cli)
            for row in snapshot["data"]["apps"]:
                try:
                    key = app_key(cli.home, row["path"], row["id"])
                    sessions = [
                        session.id
                        for session in list(self.agent.session_manager.sessions.values())
                        if getattr(session, "agent_app_framework_key", None) == key
                    ]
                    for sid in sessions:
                        await self.agent.request_run_stop(sid)
                    result = await self.request(
                        {
                            "operation": "manage",
                            "verb": "forget" if row["status"] == "missing" else "remove",
                            "path": row["path"],
                            "appId": row["id"],
                            "confirm": row["id"],
                            "stopFirst": True,
                        }
                    )
                    if result["status"] != "success" or (
                        result.get("data") or {}
                    ).get("ok") is not True:
                        raise RuntimeError(
                            result.get("stderr") or result.get("message") or "Removal failed."
                        )
                    deleted += 1
                    for sid in sessions:
                        await self.agent.delete_session(sid)
                except Exception as error:
                    failures.append(f"{row.get('name') or row['id']}: {error}")
            for sid in pending:
                session = self.agent.session_manager.get(sid)
                if session and session.agent_app_framework_pending:
                    await self.agent.delete_session(sid)
            return {"deleted": deleted, "failures": failures}
        finally:
            self.resetting = False
            await self.changed()

    async def startup(self):
        """Restore explicit startup preferences without invoking an agent."""
        # Older creation workflows were ordinary chats until scaffolding. Move
        # only those recorded by this host; titles alone never establish ownership.
        for note in self.store.all("conversation"):
            session = self.agent.session_manager.get(note.get("sessionId"))
            if (
                session is not None
                and session.type == SessionType.CHAT
                and not note.get("appId")
                and note.get("path")
                and not session.agent_app_project_id
                and not session.agent_app_framework_key
                and not session.isolated_app_task
            ):
                creation = self.store.get("creation", session.id) or {}
                self.agent.session_manager.mark_framework_creation(
                    session.id, creation.get("name") or "New app"
                )
        try:
            cli = await asyncio.to_thread(framework.configured_cli)
        except Exception:
            return  # Discovery reports a missing CLI; ordinary chat still works.
        inventory = await framework.list_apps()
        # Repair interrupted/re-scaffolded creations before a running app clears
        # their build state. The old builder (and its history) remains the owner.
        for row in (inventory.get("data") or {}).get("apps", []):
            if row.get("status") == "missing":
                continue
            builder = self._building_conversation(row["path"], cli.home)
            if builder and builder.agent_app_framework_key and builder.agent_app_framework_key != app_key(cli.home, row["path"], row["id"]):
                await self.attach(row["path"], row["id"])
        # Older receipts predate the construction screen. A promoted, verified
        # build is no longer under construction even if its live app was stopped.
        rows = (inventory.get("data") or {}).get("apps", [])
        conversations = self.store.all("conversation")
        for creation in self.store.all("creation"):
            path = creation.get("path")
            if not path:
                continue
            note = next((n for n in conversations if n.get("path") == path), None)
            if not note or note.get("home") != str(cli.home):
                continue
            running = any(row["path"] == path and row.get("status") == "running" for row in rows)
            if "building" in creation and not running:
                continue
            promoted = (self.verification(path) or {}).get("verdict") == "pass" and not self.gate_stamp(path)
            creation["building"] = not (running or promoted)
            self.store.put("creation", note["sessionId"], creation)
        registered = {
            (row["path"], row["id"])
            for row in (inventory.get("data") or {}).get("apps", [])
            if row.get("status") != "missing"
        } if inventory.get("status") == "success" else set()
        for attachment in self.store.all("attachment"):
            if attachment.get("home") != str(cli.home):
                continue
            session = self.agent.session_manager.get(attachment.get("sessionId"))
            if (attachment["path"], attachment["appId"]) in registered and self._can_bind_conversation(
                session, attachment["key"], attachment["path"],
                attachment["appId"], cli.home,
            ) and getattr(session, "agent_app_framework_key", None) != attachment["key"]:
                self.agent.session_manager.bind_framework_app(session.id, attachment["key"])
            if not (attachment.get("autoStart") or attachment.get("maintenanceResume")):
                continue
            try:
                row = await self.selected(attachment["path"], attachment["appId"])
                if row["status"] != "running":
                    result = await framework.change_app_state(
                        row["path"], row["id"], "start"
                    )
                    if result["status"] != "success":
                        raise RuntimeError(
                            result.get("message", "The app did not start.")
                        )
                attachment = await self.attach(row["path"], row["id"])
                attachment.pop("startError", None)
                attachment.pop("maintenanceResume", None)
            except Exception as error:
                attachment["startError"] = str(error)
            self.store.put("attachment", attachment["key"], attachment)
        await self.bridge.restore()
        self.maintenance.start()
        await self.changed()

    async def attach(self, path, app_id, session_id=None):
        row = await self.selected(path, app_id)
        cli = await asyncio.to_thread(framework.configured_cli)
        key = app_key(cli.home, path, app_id)
        previous = self.store.get("attachment", key) or {}
        # The app owns its side chat. Running an app command from Main or another
        # chat must never replace that conversation or move its messages there.
        # A creation owns its conversation before and throughout scaffolding.
        # Re-scaffolding can change the upstream ID without creating a new build.
        builder = self._building_conversation(path, cli.home)
        session = builder
        old_key = getattr(builder, "agent_app_framework_key", None)
        if builder and old_key != key:
            self.agent.session_manager.bind_framework_app(builder.id, key, previous_key=old_key)
        for sid in (() if builder else (previous.get("sessionId"), session_id)):
            candidate = self.agent.session_manager.get(sid) if sid else None
            if self._can_bind_conversation(candidate, key, path, app_id, cli.home):
                session = candidate
                if getattr(session, "agent_app_framework_key", None) != key:
                    self.agent.session_manager.bind_framework_app(session.id, key)
                break
        if session is None:
            session = self.agent.session_manager.create_session(
                session_type=SessionType.AGENT_APP,
                title=row["name"],
                agent_app_framework_key=key,
            )
        value = {
            **previous,
            "key": key,
            "home": str(cli.home),
            "path": path,
            "appId": app_id,
            "name": row["name"],
            "sessionId": session.id,
            "observedStatus": row.get("status"),
            "observedPort": row.get("port"),
        }
        attachment_changed = value != previous or self.store.get("conversation", session.id) != value
        if attachment_changed:
            self.store.put("attachment", key, value)
            self.store.put("conversation", session.id, value)
        if old_key and old_key != key:
            # Retire stale startup/bridge permissions; never transfer them to
            # the replacement identity. Conversation history stays in place.
            self.store.delete("attachment", old_key)
        creation = self.store.get("creation", session.id)
        build_finished = bool(creation and creation.get("building") and row.get("status") == "running")
        if build_finished:
            # Scaffolding and a dev server are not delivery. The registry's
            # verified live status ends the original construction view.
            self.store.put("creation", session.id, {**creation, "building": False})
        if attachment_changed or build_finished:
            await self.changed()
        return value

    def _building_conversation(self, path, home):
        """Resolve the single unfinished creation owned by this profile/folder."""
        candidates = []
        for note in self.store.all("conversation"):
            sid = note.get("sessionId")
            creation = self.store.get("creation", sid) if sid else None
            if not creation or not creation.get("building"):
                continue
            if (
                not note.get("home") or not note.get("path") or not creation.get("path")
                or Path(note["home"]).resolve() != Path(home).resolve()
                or Path(note["path"]).resolve() != Path(path).resolve()
                or Path(creation["path"]).resolve() != Path(path).resolve()
            ):
                continue
            session = self.agent.session_manager.get(sid)
            if (
                session is None or session.id == MAIN_SESSION_ID
                or session.type != SessionType.AGENT_APP
                or session.agent_app_project_id or session.isolated_app_task
                or self.store.get("verification_session", sid)
            ):
                continue
            bound = session.agent_app_framework_key
            if bound and bound != app_key(home, path, note.get("appId")):
                continue
            candidates.append(session)
        if len(candidates) > 1:
            raise ValueError("More than one unfinished creation owns this app directory.")
        return candidates[0] if candidates else None

    def build_info(self, session):
        """CraftBot presentation state; the framework still owns app lifecycle."""
        if session.type != SessionType.AGENT_APP:
            return None
        creation = self.store.get("creation", session.id) or {}
        if not (session.agent_app_framework_pending or creation.get("building")):
            return None
        return {
            "building": True,
            "verifying": session.agent_app_framework_key in self.verification_runs,
            "todos": [todo.to_dict() for todo in session.todos],
        }

    def _can_bind_conversation(self, session, key, path, app_id, home):
        if (
            session is None
            or session.id == MAIN_SESSION_ID
            or getattr(session, "type", None) == SessionType.MAIN
            or getattr(session, "agent_app_project_id", None)
            or getattr(session, "isolated_app_task", False)
            or self.store.get("verification_session", session.id)
        ):
            return False
        bound = getattr(session, "agent_app_framework_key", None)
        if bound:
            return bound == key
        # Upgrade the old ordinary app chat (or its creation workflow) in place.
        # General chats and conversations shared by several apps stay untouched.
        note = self.store.get("conversation", session.id) or {}
        return (
            note.get("path") == path
            and note.get("appId") in (None, app_id)
            and note.get("home") == str(home)
            and all(
                row.get("key") == key or row.get("sessionId") != session.id
                for row in self.store.all("attachment")
            )
        )

    def note(self, session_id):
        if session_id == MAIN_SESSION_ID:
            return ""  # Old attachments must not add an app context to Main.
        item = self.store.get("conversation", session_id)
        return (
            context_note(item["path"], item.get("appId", "pending creation"))
            if item
            else ""
        )

    async def workflow(
        self, activity, request, path=None, app_id=None, *, creation=None, parent_session_id=None
    ):
        if self.resetting:
            raise RuntimeError("Wait for the Agent Apps reset to finish.")
        activities = {
            "create": "creator",
            "modify": "modify",
            "operate": "operator",
            "import": "importer",
            "convert": "importer",
            "verify": "walk-verify",
        }
        if (
            activity not in activities
            or not isinstance(request, str)
            or not request.strip()
        ):
            raise ValueError("Choose an activity and describe the request.")
        if creation is not None:
            if (
                activity != "create"
                or not isinstance(creation, dict)
                or not isinstance(creation.get("name"), str)
                or not creation["name"].strip()
                or len(creation["name"]) > 200
                or "\0" in creation["name"]
                or not isinstance(creation.get("authMode"), str)
                or creation.get("authMode") not in {"none", "multi-user"}
            ):
                raise ValueError("Choose an app name and supported access mode.")
            creation = {
                "name": creation["name"].strip(),
                "authMode": creation["authMode"],
            }
        cli = await asyncio.to_thread(framework.configured_cli)
        if activity == "create":
            path = str(cli.home / "apps" / f"craftbot-{uuid.uuid4().hex[:12]}")
        stamp = None
        if activity == "verify":
            if not path or not app_id:
                raise ValueError("Select a registered candidate to verify.")
            stamp = self.gate_stamp(path)
            if not stamp or not stamp.get("budgetChecked"):
                raise ValueError(
                    "Validate the running candidate first; independent verification needs its completed gate pass."
                )
            row = await self.selected(path, app_id)
            # Selection yields to registry IO. Reset/shutdown may have begun
            # after the initial workflow guard and canceled its job snapshot.
            if self.resetting or self.closing:
                raise RuntimeError("Verification cannot start during reset or shutdown.")
            if parent_session_id:
                from app.agent_app.framework_verification import run_verification

                key = app_key(cli.home, path, app_id)
                if key in self.verification_runs:
                    raise RuntimeError("Independent verification is already running for this app.")
                task = asyncio.create_task(run_verification(self, row, stamp, request, parent_session_id))
                self.verification_runs[key] = task
                try:
                    return await task
                finally:
                    self.verification_runs.pop(key, None)
                    if not self.closing:
                        await self.changed()
            # Browser/API requests queue the work in the app's existing owner
            # conversation. That agent invokes the same action and awaits its
            # child; the HTTP/WebSocket request itself never waits for a walk.
            attached = await self.attach(path, app_id)
            from app.triggers.service import TriggerSpec
            from app.triggers.sources import TriggerSource

            await self.agent.trigger_service.emit(TriggerSpec(
                source=TriggerSource.FRAMEWORK_WORKFLOW,
                session_id=attached["sessionId"],
                description=(f"Run agent_app_framework_workflow with activity='verify', path={path!r}, app_id={app_id!r}. "
                             f"It runs an independent subagent and returns the verdict in the same action. Requested checks: {request}"),
                payload={"workflow_skills": [], "workflow_action_sets": ["agent_app"], "run_source": "framework_workflow"},
            ))
            await self.changed()
            return {"sessionId": attached["sessionId"], "path": path, "queued": True}
        if path and app_id:
            attached = await self.attach(path, app_id)
            session = self.agent.session_manager.get(attached["sessionId"])
        else:
            session = self.agent.session_manager.create_session(
                session_type=SessionType.AGENT_APP if activity == "create" else SessionType.CHAT,
                title=(creation or {}).get("name", "New app") if activity == "create" else f"Agent App: {activity}",
                agent_app_framework_pending=activity == "create",
            )
        if path:
            self.store.put(
                "conversation",
                session.id,
                {
                    "path": path,
                    "appId": app_id,
                    "home": str(cli.home),
                    "sessionId": session.id,
                },
            )
        if activity == "create":
            self.store.put("creation", session.id, {"path": path, **(creation or {}), "building": True})
        from app.triggers.service import TriggerSpec
        from app.triggers.sources import TriggerSource

        prompt = (
            f"Use the unchanged framework-{activities[activity]} skill.\n{request}\n"
        )
        if activity == "create":
            prompt += "The destination below is allocated but DOES NOT EXIST yet. Discover the blueprints and scaffold it with the existing CLI before following the creator workflow.\n"
            if creation:
                prompt += "CraftBot binds the selected name and access mode to this destination's scaffold command. Use agent_app_command for scaffolding; do not replace the user's selections.\n"
        if path:
            prompt += context_note(path, app_id or "new app")
        await self.agent.trigger_service.emit(
            TriggerSpec(
                source=TriggerSource.FRAMEWORK_WORKFLOW,
                session_id=session.id,
                description=prompt,
                payload={
                    "workflow_skills": [f"framework-{activities[activity]}"],
                    "workflow_action_sets": [
                        *(["agent_app"] if activity != "operate" else []),
                        "a2app",
                        "file_operations",
                        "shell",
                        "mini_browser",
                    ],
                    "run_source": "framework_workflow",
                },
            )
        )
        await self.changed()
        return {"sessionId": session.id, "path": path}

    def scaffold_arguments(self, session_id, args):
        """Carry explicit form choices into the unchanged CLI's scaffold flags."""
        creation = self.store.get("creation", session_id) if session_id else None
        if not creation or "name" not in creation or "authMode" not in creation or Path(args[0]).resolve() != Path(creation["path"]).resolve():
            return args
        result = list(args)
        for flag, value in (
            ("--name", creation["name"]),
            ("--auth-mode", creation["authMode"]),
        ):
            if flag in result:
                at = result.index(flag)
                if at + 1 >= len(result) or result[at + 1] != value:
                    raise ValueError(f"Use the user's selected {flag}: {value}")
            else:
                result.extend([flag, value])
        return result

    @staticmethod
    def gate_stamp(path):
        try:
            return json.loads(
                (Path(path) / ".a2app" / "gate-pass.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def verification(self, path):
        return self.store.get("verification", str(Path(path).resolve()))

    def report_verification(self, session_id, verdict, evidence):
        assignment = self.store.get("verification_session", session_id)
        if not assignment:
            raise PermissionError(
                "Only the assigned independent verifier can record this verdict."
            )
        if assignment.get("mode") == "subagent" and assignment.get("status") != "running":
            raise PermissionError("This verification subagent has already ended.")
        if (
            verdict not in {"pass", "defects", "incomplete", "blocked"}
            or not isinstance(evidence, str)
            or not evidence.strip()
        ):
            raise ValueError("A verifier verdict and supporting evidence are required.")
        if (
            verdict == "pass"
            and self.gate_stamp(assignment["path"]) != assignment["stamp"]
        ):
            raise ValueError(
                "The validation stamp changed during verification. Verify the current candidate again."
            )
        result = {
            **assignment,
            "sessionId": session_id,
            "verdict": verdict,
            "evidence": evidence,
            "at": time.time(),
        }
        self.store.put("verification", str(Path(assignment["path"]).resolve()), result)
        return result

    def require_verified(self, path):
        result = self.verification(path)
        if (
            not result
            or result.get("verdict") != "pass"
            or result["stamp"] != self.gate_stamp(path)
        ):
            raise ValueError(
                "Independent verification has not passed for this validation stamp. Run agent_app_framework_workflow(activity='verify') to await the independent verification subagent before promotion."
            )

    async def verification_reported(self, result):
        """Return the independent result to its builder through the normal queue."""
        if result.get("mode") == "subagent":
            return  # The waiting parent receives the result as its action output.
        builder = result.get("builderSessionId")
        if not builder or not self.agent.session_manager.get(builder):
            return
        from app.triggers.service import TriggerSpec
        from app.triggers.sources import TriggerSource

        await self.agent.trigger_service.emit(
            TriggerSpec(
                source=TriggerSource.FRAMEWORK_WORKFLOW,
                session_id=builder,
                description=f"Independent verification for {result['path']} returned {result['verdict']}. Evidence: {result['evidence']}\nContinue the framework workflow. A pass authorizes promotion only while its validation stamp remains current; successful serving is required before announcing delivery. For defects, repair and request a new independent verification. For incomplete/blocked, explain the remaining check or blocker without claiming readiness.",
                payload={
                    "workflow_skills": [],
                    "workflow_action_sets": ["agent_app", "a2app", "mini_browser"],
                    "run_source": "framework_workflow",
                },
                dedup_key=f"framework-verdict:{result['sessionId']}:{result['at']}",
            )
        )
        await self.changed()

    async def snapshot(self):
        cli = await asyncio.to_thread(framework.configured_cli)
        return {
            "migrations": [
                m for m in self.store.all("migration") if m.get("home") == str(cli.home)
            ],
            "attachments": [
                a
                for a in self.store.all("attachment")
                if a.get("home") == str(cli.home)
            ],
            "jobs": [
                j for j in self.store.all("install") if j.get("home") == str(cli.home)
            ],
            "deliveries": [
                d for d in self.store.all("delivery") if d.get("home") == str(cli.home)
            ][-50:],
        }

    async def start_install(self, request, request_id):
        if self.resetting:
            raise RuntimeError("Wait for the Agent Apps reset to finish.")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 100:
            raise ValueError("An install request ID is required.")
        if bool(request.get("id")) == bool(request.get("from")):
            raise ValueError("Choose one catalogue ID or package source.")
        cli = await asyncio.to_thread(framework.configured_cli)
        args = ["install"]
        if request.get("id"):
            if str(request["id"]).startswith("-"):
                raise ValueError("Invalid catalogue ID.")
            args.append(str(request["id"]))
        else:
            args.extend(["--from", str(request["from"])])
        for field in ("source", "into", "name"):
            if request.get(field):
                args.extend([f"--{field}", str(request[field])])
        for key, value in (request.get("set") or {}).items():
            args.extend(["--set", f"{key}={value}"])
        if request.get("noStart") is True:
            args.append("--no-start")
        args.append("--events")
        job = {
            "id": request_id,
            "home": str(cli.home),
            "request": request,
            "status": "running",
            "steps": [],
            "startedAt": time.time(),
            "result": None,
        }
        if not self.store.insert("install", request_id, job):
            previous = self.store.get("install", request_id)
            if previous["request"] != request or previous["home"] != str(cli.home):
                raise ValueError(
                    "This request ID was already used for another installation."
                )
            return previous
        self.jobs[request_id] = asyncio.create_task(self._install(cli, args, job))
        return job

    async def _install(self, cli, args, job):
        def line(text):
            try:
                event = json.loads(text)
            except ValueError:
                return
            if not isinstance(event, dict):
                return
            if event.get("event") == "step":
                job["steps"] = [
                    s for s in job["steps"] if s.get("step") != event.get("step")
                ][-30:] + [event]
            elif event.get("event") == "result":
                job["result"] = event
            else:
                return
            self.store.put("install", job["id"], job)

        try:
            result = await cli.run(
                "agent-app",
                args,
                cwd=cli.package_dir,
                timeout=3600,
                on_stdout_line=line,
            )
            doc = job["result"] or {}
            job.update(
                status="success" if result.ok and doc.get("ok") else "error",
                stderr=result.stderr,
                exitCode=result.code,
            )
            if not doc:
                job["error"] = (
                    result.stderr
                    or "Installation ended without a result. Inspect before retrying."
                )
            # A failed gate can leave a repairable registered app. Attach it too,
            # without turning a failed/unchecked gate into a ready announcement.
            if doc.get("dir") and doc.get("id"):
                try:
                    attached = await self.attach(doc["dir"], doc["id"])
                    job["sessionId"] = attached["sessionId"]
                except Exception as exc:
                    job["linkError"] = str(exc)
        except asyncio.CancelledError:
            job.update(
                status="interrupted",
                error="Installation interrupted; inspect the registry and destination before retrying.",
            )
            raise
        except Exception as exc:
            job.update(status="error", error=str(exc))
        finally:
            job["endedAt"] = time.time()
            self.store.put("install", job["id"], job)
            self.jobs.pop(job["id"], None)
            if not self.closing:
                await self.changed()

    async def request(self, data):
        operation = data.get("operation")

        if operation == "snapshot":
            return await self.snapshot()
        if operation == "task_status":
            return await self.bridge.request_status(data["path"], data["appId"])
        if operation == "maintenance":
            return await self.maintenance.info(data["path"], data["appId"])
        if operation == "sharing":
            path, app_id = data["path"], data["appId"]
            async with framework.lifecycle_lock(path):
                await self.selected(path, app_id)
                if data.get("action") == "info":
                    return self.sharing.links(path, app_id)
                if data.get("action") == "open":
                    result = await self.sharing.open(path, app_id, data["channel"])
                    await self.changed()
                    return result
                if data.get("action") == "close":
                    return await self.sharing.close(path, app_id, data["channel"])
                raise ValueError("Choose open or close sharing.")
        if operation == "backup_delete":
            return await self.maintenance.backup(
                data["path"], data["appId"], "delete", data.get("backupId")
            )
        if operation == "details":
            row = await self.selected(data["path"], data["appId"])
            manifest = json.loads(
                await asyncio.to_thread(
                    (Path(row["path"]) / "manifest.json").read_text, encoding="utf-8"
                )
            )
            return {
                "capabilities": {
                    "declared": {
                        name: value
                        for name, value in manifest.get("capabilities", {}).items()
                        if isinstance(value, dict)
                    },
                },
            }
        if operation == "review_delivery":
            cli = await asyncio.to_thread(framework.configured_cli)
            receipt = self.store.get("delivery", data["key"])
            if (
                not receipt
                or receipt.get("home") != str(cli.home)
                or receipt.get("status") != "interrupted"
                or data.get("confirm") != receipt["taskId"]
            ):
                raise ValueError(
                    "Confirm an interrupted task in this profile before allowing another attempt."
                )
            receipt["retryApproved"] = True
            self.store.put("delivery", receipt["key"], receipt)
            return receipt
        if operation == "attach":
            return await self.attach(data["path"], data["appId"])
        if operation == "preference":
            attachment = await self.attach(data["path"], data["appId"])
            attachment = self.maintenance.patch(attachment, data)
            await self.changed()
            return attachment
        if operation == "workflow":
            return await self.workflow(
                data["activity"],
                data["request"],
                data.get("path"),
                data.get("appId"),
                creation=data.get("creation"),
            )
        if operation == "install":
            return await self.start_install(data["package"], data["requestId"])
        if operation in {"catalogue", "inspect"}:
            args = [operation]
            for key in ("search", "source", "from"):
                if data.get(key):
                    args.extend([f"--{key}", str(data[key])])
            if data.get("id"):
                if str(data["id"]).startswith("-"):
                    raise ValueError("Invalid catalogue ID.")
                args.append(str(data["id"]))
            return await command("agent-app", args)
        if operation == "manage":
            verb = data.get("verb")
            row = await self.selected(
                data["path"], data["appId"], allow_missing=verb == "forget"
            )
            if verb not in {
                "backup",
                "restore",
                "export",
                "remove",
                "forget",
                "validate",
                "owner",
                "invite",
            }:
                raise ValueError("Unsupported management command.")
            args = [data["path"], verb]
            if verb == "forget":
                if data.get("confirm") != data["appId"] or (
                    row["status"] != "missing" and data.get("keepFiles") is not True
                ):
                    raise ValueError(
                        "Confirm the current app and choose to keep its files before removing it from the list."
                    )
            if verb in {"backup", "restore"}:
                return await self.maintenance.backup(
                    data["path"], data["appId"], verb, data.get("backupId")
                )
            if verb == "remove" or (verb == "forget" and data.get("keepFiles") is True):
                if data.get("confirm") != data["appId"]:
                    raise ValueError("Confirm the selected app ID before removal.")
                if data.get("stopFirst") is True and row["status"] in {
                    "running",
                    "stopped",
                }:
                    # The sidebar confirmation covers stopping the live app.
                    # Upstream still owns removal and its data/archive guards.
                    stopped = await framework.change_app_state(
                        data["path"], data["appId"], "stop"
                    )
                    await self.changed()
                    if stopped["status"] != "success":
                        raise RuntimeError(
                            stopped.get("message") or "The app could not be stopped."
                        )
                    await self.selected(data["path"], data["appId"])
                if verb == "remove":
                    await self.maintenance.before_remove(data["path"], data["appId"])
                    # A bare stop intentionally leaves the dev candidate alive.
                    # Deleting the app abandons that candidate too; its process
                    # otherwise holds the directory open on Windows.
                    stopped_dev = await command(
                        "agent-app", [data["path"], "stop", "--dev"]
                    )
                    if (
                        stopped_dev["status"] != "success"
                        or (stopped_dev.get("data") or {}).get("ok") is not True
                    ):
                        raise RuntimeError(
                            stopped_dev.get("stderr")
                            or stopped_dev.get("message")
                            or "The app's development instance could not be stopped."
                        )
                    await self.selected(data["path"], data["appId"])
                    args.append("--yes")
            if verb == "export":
                destination = (
                    self.store.path.parent / "exports" / f"{uuid.uuid4().hex}.zip"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                args.extend(["--out", str(destination)])
            result = await command("agent-app", args)
            if (
                verb in {"remove", "forget"}
                and result["status"] == "success"
                and (result.get("data") or {}).get("ok") is True
            ):
                cli = await asyncio.to_thread(framework.configured_cli)
                key = app_key(cli.home, data["path"], data["appId"])
                attachment = self.store.get("attachment", key)
                if attachment:
                    # Keep the conversation, but never restart a deleted app
                    # or restore its old task permissions on a later launch.
                    attachment.update(
                        autoStart=False,
                        tasksAllowed=False,
                        ownerToolsAllowed=False,
                        backupsEnabled=False,
                    )
                    attachment.pop("startError", None)
                    attachment.pop("bridgeError", None)
                    attachment.pop("maintenanceResume", None)
                    self.store.put("attachment", key, attachment)
            await self.changed()
            return result
        if operation == "consent" and self.bridge:
            return await self.bridge.consent(
                data["path"],
                data["appId"],
                data.get("allow") is True,
                data.get("ownerTools") if "ownerTools" in data else None,
                data.get("revision"),
                data.get("reviewId"),
            )
        raise ValueError("Unknown framework request.")

    async def close(self):
        global _host
        if self.closing:
            return
        self.closing = True
        await self.maintenance.close()
        await self.sharing.shutdown()
        if self.restoring:
            self.restoring.cancel()
            await asyncio.gather(self.restoring, return_exceptions=True)
        tasks = [*self.jobs.values(), *self.verification_runs.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.bridge:
            await self.bridge.close()
        if _host is self:
            _host = None
