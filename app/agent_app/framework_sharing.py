"""Link grants at CraftBot's gateway, without changing an Agent-App project.

The gateway checks the link and browser origin before forwarding. It never
injects an admin token: multi-user apps still require their own account login.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import urlsplit

from aiohttp import web

from app.agent_app import framework
from app.agent_app.sharing import LanChannel, LanRelay, TunnelChannel
from app.process_ledger import kill_tree


class ShareGateway(LanRelay):
    def __init__(self, port, app_id, host="127.0.0.1"):
        super().__init__(host, 0, port)
        self.origin = ""  # Reject everything until the transport is ready.
        self.app_id = app_id
        self.secret = secrets.token_urlsafe(32)
        self.cookie = (
            "craftbot_share_"
            + hashlib.sha256((app_id + self.secret).encode()).hexdigest()[:16]
        )
        self.sockets = set()

    async def _handle(self, request):
        if not self.origin or request.host != urlsplit(self.origin).netloc:
            return web.Response(status=403, text="This share link is closed.")
        supplied = request.query.get("a2app_share", "")
        if (
            supplied
            and request.method == "GET"
            and secrets.compare_digest(supplied.encode(), self.secret.encode())
        ):
            target = request.rel_url.with_query(
                [(k, v) for k, v in request.query.items() if k != "a2app_share"]
            )
            response = web.HTTPSeeOther(location=str(target))
            response.set_cookie(
                self.cookie,
                self.secret,
                httponly=True,
                samesite="Lax",
                secure=self.origin.startswith("https:"),
                path="/",
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            raise response
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        ref_origin = None
        if referer:
            parsed = urlsplit(referer)
            ref_origin = f"{parsed.scheme}://{parsed.netloc}"
        if (origin and origin != self.origin) or (
            ref_origin and ref_origin != self.origin
        ):
            return web.Response(status=403, text="Open the app using its share link.")
        if request.headers.get(
            "Sec-Fetch-Site"
        ) == "cross-site" and request.method not in {"GET", "HEAD"}:
            return web.Response(status=403)
        if not secrets.compare_digest(
            request.cookies.get(self.cookie, "").encode(), self.secret.encode()
        ):
            return web.Response(
                status=401, text="Use the complete share link from CraftBot."
            )
        # Cookie-authenticated mutations must carry same-origin evidence.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not (
            origin or ref_origin
        ):
            return web.Response(status=403, text="A same-origin request is required.")
        try:
            async with self._session.get(
                self.upstream + "/api/_a2app", timeout=3, allow_redirects=False
            ) as response:
                identity = await response.json()
                if (
                    response.status != 200
                    or identity.get("a2app") is not True
                    or identity.get("app", {}).get("id") != self.app_id
                ):
                    return web.Response(
                        status=502, text="The shared app is no longer running here."
                    )
        except Exception:
            return web.Response(status=502, text="The shared app is not running.")
        task = asyncio.current_task()
        self.sockets.add(task)
        try:
            return await super()._handle(request)
        finally:
            self.sockets.discard(task)

    def _forward_headers(self, request, drop=()):
        headers = super()._forward_headers(request, drop)
        # Present one verified same-origin view to the unchanged adapter. Never
        # promote a visitor to owner or forward spoofed proxy/security headers.
        for key in list(headers):
            if key.lower().startswith(
                ("x-forwarded-", "sec-fetch-")
            ) or key.lower() in {"forwarded", "host", "origin", "referer", "cookie"}:
                del headers[key]
        headers["Host"] = urlsplit(self.upstream).netloc
        headers["Origin"] = self.upstream
        cookies = SimpleCookie()
        for key, value in request.cookies.items():
            if not key.startswith("craftbot_share_"):
                cookies[key] = value
        if cookies:
            headers["Cookie"] = "; ".join(m.OutputString() for m in cookies.values())
        return headers

    def _response_headers(self, headers):
        for key, value in headers.items():
            if key.lower() in {
                "location",
                "content-location",
                "access-control-allow-origin",
            }:
                value = value.replace(self.upstream, self.origin)
            if key.lower() == "referrer-policy":
                continue
            yield key, value
        yield "Referrer-Policy", "no-referrer"

    async def stop(self):
        self.origin = ""
        if self._loop:
            # Revoke existing streams and WebSockets as well as new requests.
            def cancel():
                for task in list(self.sockets):
                    task.cancel()

            self._loop.call_soon_threadsafe(cancel)
        await super().stop()


class FrameworkSharing:
    def __init__(self, host, legacy_manager=None):
        self.host = host
        # Share the transport instance so orphan cleanup never kills a live
        # tunnel belonging to another CraftBot app runtime.
        self.tunnel = (
            legacy_manager.sharing.channel("tunnel")
            if legacy_manager is not None
            else TunnelChannel(lambda proc: kill_tree(proc.pid, grace=0))
        )
        self.active = {}

    def channels(self, path, app_id):
        return [channel for p, i, channel in self.active if p == path and i == app_id]

    def links(self, path, app_id):
        return {
            channel: self.active[(path, app_id, channel)]["link"]
            for channel in self.channels(path, app_id)
        }

    async def open(self, path, app_id, channel):
        if channel not in {"lan", "tunnel"}:
            raise ValueError("Choose LAN or public sharing.")
        row = await self.host.selected(path, app_id)
        if row["status"] == "stopped":
            started = await framework.change_app_state_locked(path, app_id, "start")
            if started["status"] != "success":
                raise ValueError(
                    started.get("message", "The app could not be started for sharing.")
                )
        selected = await framework.open_app_view(path, app_id)
        if selected["status"] != "success":
            raise ValueError(
                selected.get("message", "Start the app before sharing it.")
            )
        port = urlsplit(selected["data"]["url"]).port
        await self.close(path, app_id, channel)
        address = LanChannel.lan_ip() if channel == "lan" else "127.0.0.1"
        if not address:
            raise ValueError("This computer is not connected to a local network.")
        gateway = ShareGateway(port, app_id, address)
        identity = (
            "framework-" + hashlib.sha256(f"{path}:{app_id}".encode()).hexdigest()
        )
        project = SimpleNamespace(
            id=identity, path=str(self.host.store.path.parent / "shares" / identity)
        )
        try:
            bound = await gateway.start()
            origin = (
                f"http://{address}:{bound}"
                if channel == "lan"
                else await self.tunnel._connect(project, bound)
            )
            gateway.origin = origin
            link = f"{origin}/?a2app_share={gateway.secret}"
            self.active[(path, app_id, channel)] = {
                "gateway": gateway,
                "project": project,
                "link": link,
            }
            return self.links(path, app_id)
        except BaseException:
            await gateway.stop()
            if channel == "tunnel":
                await self.tunnel._disconnect(project)
            raise

    async def close(self, path, app_id, channel):
        if channel not in {"lan", "tunnel"}:
            raise ValueError("Choose LAN or public sharing.")
        state = self.active.pop((path, app_id, channel), None)
        if state:
            await state["gateway"].stop()
            if channel == "tunnel":
                await self.tunnel._disconnect(state["project"])
        return self.links(path, app_id)

    async def close_app(self, path, app_id):
        for channel in self.channels(path, app_id):
            await self.close(path, app_id, channel)

    async def shutdown(self):
        for path, app_id, channel in list(self.active):
            await self.close(path, app_id, channel)
