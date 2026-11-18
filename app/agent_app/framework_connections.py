"""URL connections using upstream login, credentials and task delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout


def is_connection(target: str) -> bool:
    return str(target).startswith(("http://", "https://"))


def connection_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter the HTTP or HTTPS URL of a running Agent App, without credentials.")
    # Agent-App credentials and identity pins are keyed by origin.
    port = parsed.port
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
    return f"{parsed.scheme}://{host}{suffix}"


_SOURCE = re.compile(r"(?:([a-z][a-z0-9+.-]*)://)?(\*|(?:\*\.)?[a-z0-9.-]+)(?::(\*|\d+))?(/\S*)?")


def _source_allows(source: str, page_origin: str, embedder: str) -> bool:
    """One CSP source expression against the origin of the page that frames."""
    source = source.lower()
    frame = urlsplit(embedder)
    if source == "'self'":
        return embedder == page_origin
    if source == "*":
        return frame.scheme in {"http", "https"}
    if re.fullmatch(r"[a-z][a-z0-9+.-]*:", source):  # a scheme source, e.g. https:
        return frame.scheme == source[:-1] or (source == "http:" and frame.scheme == "https")
    match = _SOURCE.fullmatch(source)
    if not match:
        return False  # 'none', nonces and hashes name no origin
    scheme, host, port, path = match.groups()
    scheme = scheme or urlsplit(page_origin).scheme
    if frame.scheme != scheme and not (scheme == "http" and frame.scheme == "https"):
        return False
    hostname = frame.hostname or ""
    if host != "*" and not (hostname.endswith(host[1:]) if host.startswith("*.") else hostname == host):
        return False
    if port != "*":
        defaults = {"http": 80, "https": 443}
        wanted = int(port) if port else defaults.get(scheme)
        actual = frame.port or defaults.get(frame.scheme)
        if wanted != actual and not (wanted == 80 and actual == 443):
            return False
    return path in (None, "/")


def frame_ancestors_allow(headers, page_origin: str, embedder: str) -> bool:
    """Whether a page served with these headers lets `embedder` frame it: every
    CSP `frame-ancestors` must allow it; without one, X-Frame-Options decides."""
    ancestors = []
    for value in headers.getall("Content-Security-Policy", []):
        for policy in value.split(","):
            for directive in policy.split(";"):
                name, *sources = directive.split() or [""]
                if name.lower() == "frame-ancestors":
                    ancestors.append(sources)
                    break
    if not ancestors:
        option = headers.get("X-Frame-Options", "").strip().lower()
        return option not in {"deny", "sameorigin"} or (option == "sameorigin" and embedder == page_origin)
    return all(any(_source_allows(source, page_origin, embedder) for source in sources) for sources in ancestors)


async def frame_allowed(url: str, embedder: str) -> bool:
    """Whether CraftBot's page at `embedder` may show `url` in a frame. Unknown is no."""
    try:
        embedder = connection_url(embedder)
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with session.get(url.split("#")[0]) as response:
                return response.ok and frame_ancestors_allow(
                    response.headers, connection_url(str(response.url)), embedder)
    except Exception:
        return False


def connection_rows(connected: list[dict]) -> list[dict]:
    return [
        {"id": row["appId"], "name": row["name"], "path": row["origin"],
         "url": row["origin"], "connection": row,
         "status": "running" if row["status"] == "online" else "unreachable"}
        for row in connected if row.get("appId")
    ]


async def connection_transport(cli, path, app_id, mode, *, endpoint="", token=""):
    from app.agent_app.framework_local_credential import _private_transport
    return await _private_transport(cli, path, app_id, mode, endpoint=endpoint, token=token)


async def connection_info(cli, path, app_id):
    return json.loads(await connection_transport(cli, path, app_id, "info"))


async def connection_revision(cli, path, app_id):
    data = await connection_info(cli, path, app_id)
    identity, who = data["identity"], data["who"]
    return hashlib.sha256(json.dumps([
        app_id, identity.get("protocol"), identity.get("app", {}).get("version"), identity.get("schemaVersion"),
        who.get("credentialId"), who.get("principal"), sorted(who.get("scopes", [])),
    ]).encode()).hexdigest()


class FrameworkConnections:
    def __init__(self, host):
        self.host = host
        self.attempts = {}
        self.tasks = {}
        self.pumps = {}
        self.lock = asyncio.Lock()

    async def start(self, url, embedder=""):
        from app.agent_app import framework

        origin = connection_url(url)
        async with self.lock:
            if len(self.attempts) > 50:
                self.attempts = {key: value for key, value in self.attempts.items() if value["status"] == "pending"}
            for attempt in self.attempts.values():
                if attempt["origin"] == origin and attempt["status"] == "pending":
                    return attempt
            cli = await asyncio.to_thread(framework.configured_cli)
            snapshot = await framework._list_apps(cli)
            if snapshot["status"] != "success":
                raise RuntimeError(snapshot["message"])
            for row in snapshot["data"]["apps"]:
                local_origin = f"http://127.0.0.1:{row.get('port')}" if not row.get("connection") else ""
                same_local = origin.replace("http://localhost:", "http://127.0.0.1:") == local_origin
                if (row.get("url") == origin or same_local) and row["status"] == "running":
                    if row.get("connection"):
                        try:
                            await connection_info(cli, origin, row["id"])
                        except PermissionError:
                            continue  # Expired/revoked grants need another approval.
                    attachment = await self.host.attach(row["path"], row["id"])
                    return {"status": "connected", "attachment": attachment}
            attempt = {"id": uuid.uuid4().hex, "origin": origin, "status": "pending"}
            self.attempts[attempt["id"]] = attempt
            ready = asyncio.Event()
            self.tasks[attempt["id"]] = asyncio.create_task(self._login(cli, attempt, ready))
        try:
            await asyncio.wait_for(ready.wait(), 35)
        except asyncio.TimeoutError:
            await self.cancel(attempt["id"])
            raise ValueError("The app did not respond. Check its URL and try again.") from None
        if attempt.get("approvalUrl"):
            # Approve inside CraftBot's page when the app lets it frame its
            # approval page; otherwise the person approves in a tab.
            attempt["embeddable"] = await frame_allowed(attempt["approvalUrl"], embedder)
        return attempt

    async def _login(self, cli, attempt, ready):
        outcome = {}

        def event(line):
            try:
                value = json.loads(line)
            except ValueError:
                return
            if value.get("event") == "approve":
                # Only expose the app's approval page; device codes/tokens stay in the CLI.
                url = value.get("url") or value.get("verificationUriComplete")
                if url and connection_url(url) == attempt["origin"]:
                    attempt["approvalUrl"] = url
                    ready.set()
            elif value.get("event") == "result":
                if value.get("ok"):
                    attempt["finishing"] = True  # signed in; adding the app takes a moment
                else:
                    outcome["error"] = value.get("error")

        try:
            result = await cli.run("a2app", [attempt["origin"], "login", "--print-only", "--events", "--name", "CraftBot"],
                                   cwd=cli.package_dir, timeout=650, on_stdout_line=event)
            if not result.ok:
                # The sign-in's own reason; before it starts there is none, only
                # the CLI's error lines (its info lines repeat the link and code).
                errors = [line.removeprefix("✗ ") for line in result.stderr.strip().splitlines() if not line.startswith("ℹ")]
                raise RuntimeError(outcome.get("error") or "\n".join(errors).strip()
                                   or "The app did not approve access. Try connecting again.")
            from app.agent_app import framework
            snapshot = await framework._list_apps(cli)
            row = next((r for r in snapshot.get("data", {}).get("apps", []) if r.get("url") == attempt["origin"]), None)
            if row is None:
                raise RuntimeError("The app approved access but could not be found in the framework registry.")
            attempt.update(status="connected", attachment=await self.host.attach(row["path"], row["id"]))
        except asyncio.CancelledError:
            attempt["status"] = "cancelled"
            raise
        except Exception as error:
            attempt.update(status="error", error=str(error))
        finally:
            if attempt["status"] != "pending":
                attempt.pop("approvalUrl", None)
                attempt.pop("finishing", None)
            ready.set()
            self.tasks.pop(attempt["id"], None)
            await self.host.changed()

    async def cancel(self, attempt_id):
        task = self.tasks.get(attempt_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.attempts.get(attempt_id, {"status": "cancelled"})

    async def stop_pump(self, path):
        task = self.pumps.pop(path, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def start_pump(self, path, app_id):
        await self.stop_pump(path)
        self.pumps[path] = asyncio.create_task(self._pump(path, app_id))

    async def _pump(self, path, app_id):
        from app.agent_app import framework
        from app.agent_app.framework_store import app_key
        cli = await asyncio.to_thread(framework.configured_cli)
        bridge = self.host.bridge
        key = app_key(cli.home, path, app_id)
        while not self.host.closing:
            grant = self.host.store.get("attachment", key)
            if not grant or not grant.get("tasksAllowed"):
                return
            try:
                if grant.get("capabilityFingerprint") != await connection_revision(cli, path, app_id):
                    raise PermissionError("The app or its access changed. Review app task permissions again.")
                if grant.pop("bridgeError", None):
                    self.host.store.put("attachment", key, grant)
                    await self.host.changed()
                await connection_transport(cli, path, app_id, "pump", endpoint=bridge.endpoint, token=bridge.token)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                grant = self.host.store.get("attachment", key)
                if grant and grant.get("bridgeError") != str(error):
                    grant["bridgeError"] = str(error)
                    self.host.store.put("attachment", key, grant)
                    await self.host.changed()
            # Upstream handles outages once connected. Retry initial connection
            # failures here too, including an app offline when CraftBot starts.
            await asyncio.sleep(5)

    async def close(self):
        tasks = [*self.tasks.values(), *self.pumps.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
