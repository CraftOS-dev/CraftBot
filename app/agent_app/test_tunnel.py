"""Public sharing (TunnelChannel): the output sink and the shared-origin grant.

Four failures this pins down, all observed live on 2026-08-28. Each one alone
was enough to make a shared app unusable, and the first hid the other three:

  1. cloudflared was spawned with stdout/stderr on PIPEs, and the reader
     thread RETURNED as soon as it matched the public URL. Nothing drained
     those pipes afterwards, so cloudflared blocked on its next write once the
     OS buffer filled (4 KB by default on Windows) and quietly stopped
     proxying. The process still looked alive; remote visitors just hung until
     their client timed out, and the bytes explaining why were stuck in the
     buffer — which is also why there was no log of any of it.

  2. Sharing aimed at `backend_port`, a port left over from the old
     vite+backend split that nothing binds. The app was up on `port` the
     whole time. (§5)

  3. cloudflared was pointed at `http://localhost:<port>`, which it resolves
     to ::1 first on Windows, while both PocketBase and the external proxy
     bind 127.0.0.1. Not testable here: it lives in the argv of one Popen
     call, guarded by a comment.

  4. The origin guard allowed loopback origins only. Browsers send `Origin`
     on same-origin writes too, so through a tunnel the app LOADED (a GET
     carries no Origin) and then 403'd every save. (§3, §4)

And one observed live 2026-10-02..06:

  5. The public URL was scraped from cloudflared's output with a pattern for
     *.trycloudflare.com. When DNS sent the quick-tunnel request to a host
     that refused it, cloudflared logged a failure naming
     https://api.trycloudflare.com/tunnel and exited; the pattern matched
     that, and the owner was handed a link to Cloudflare's API host. (§6)

Run:  python -m app.agent_app.test_tunnel

Style follows app/agent_app/test_data_safety.py: a module-level assert
script with hand-rolled stubs, no pytest.
"""

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Windows consoles default to cp1252; the checks print arrows and dashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.agent_app.a2app_proxy import ExternalA2AppProxy
from app.agent_app.manager import AgentAppManager, AgentAppProject
from app.agent_app.sharing import ShareError, ShareGrant, TunnelChannel

# A stand-in for cloudflared: its metrics server (/ready, /quicktunnel), then
# far more chatter than any pipe buffer holds. This is the exact output shape
# that used to wedge. With --never-ready it has a hostname but no connection
# to Cloudflare, so /ready answers 503, as the real one does.
FAKE_CLOUDFLARED = r"""
import http.server, json, sys, threading
host, port = sys.argv[sys.argv.index("--metrics") + 1].rsplit(":", 1)
connected = "--never-ready" not in sys.argv
asked = threading.Event()

class Metrics(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ready":
            status = 200 if connected else 503
            body = {"status": status, "readyConnections": int(connected)}
        elif self.path == "/quicktunnel":
            status, body = 200, {"hostname": "fake-tunnel-for-tests.trycloudflare.com"}
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        if self.path == "/quicktunnel":
            asked.set()  # only once answered: the main thread exits on it

    def log_message(self, *args):
        pass

server = http.server.HTTPServer((host, int(port)), Metrics)
threading.Thread(target=server.serve_forever, daemon=True).start()
for i in range(4000):
    sys.stderr.write("INF served request %d %s\n" % (i, "x" * 60))
sys.stderr.write("DONE\n")
sys.stderr.flush()
asked.wait(20)
"""

# Verbatim from cloudflared.log on 2026-10-02: the failure that came back as
# a link. It stays up a moment, as the real one does, so the line is on disk
# while the process still looks alive.
FAILED_REQUEST = r"""
import sys, time
sys.stderr.write("INF Requesting new quick Tunnel on trycloudflare.com...\n")
sys.stderr.write('failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": '
                 'dial tcp 18.204.152.241:443: connectex: No connection could be made because '
                 'the target machine actively refused it.\n')
sys.stderr.flush()
time.sleep(1.5)
sys.exit(1)
"""

URL = "https://fake-tunnel-for-tests.trycloudflare.com"


def _fixture(tmp: Path) -> "tuple[TunnelChannel, AgentAppProject, Path]":
    (tmp / "logs").mkdir(exist_ok=True)
    fake = tmp / "fake_cloudflared.py"
    fake.write_text(FAKE_CLOUDFLARED, encoding="utf-8")
    channel = TunnelChannel(terminate=lambda proc: proc.kill())
    project = AgentAppProject(id="testproj", name="T", description="", path=str(tmp))
    return channel, project, fake


async def _check_sink(tmp: Path) -> None:
    channel, project, fake = _fixture(tmp)

    handle, log_path = channel._open_log(project, 3101)
    assert handle is not None, "no sink means no log"
    assert log_path == tmp / "logs" / "cloudflared.log", log_path

    metrics = f"127.0.0.1:{channel._free_loopback_port()}"
    proc = subprocess.Popen(
        [sys.executable, str(fake), "--metrics", metrics],
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    url = await channel._await_ready(proc, metrics, log_path, timeout=20)
    assert url == URL, url

    # THE regression: the child must run to completion, not block on output.
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("cloudflared blocked on its output — deadlock is back")
    channel._close_log(handle)

    body = log_path.read_text(encoding="utf-8", errors="replace")
    assert "=== cloudflared start" in body, "session header missing"
    assert body.rstrip().endswith("DONE"), "log truncated: tail=%r" % body[-80:]
    assert len(body) > 300_000, "only %d bytes captured" % len(body)


print_sink = "§1 cloudflared output is captured, never buffered: OK"


async def _check_failure_paths(tmp: Path) -> None:
    channel, project, _ = _fixture(tmp)

    # A cloudflared that dies before its tunnel is ready must fail fast, not
    # sit out the whole timeout: the launch path is awaiting this.
    dead = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    dead.wait()
    url = await channel._await_ready(
        dead, "127.0.0.1:1", tmp / "absent.log", timeout=30
    )
    assert url is None, url

    # The log is append-mode across restarts, but capped.
    log_path = channel.log_path(project)
    log_path.write_text("y" * 2_500_000, encoding="utf-8")
    handle, _ = channel._open_log(project, 3101)
    channel._close_log(handle)
    size = log_path.stat().st_size
    assert size < 1000, "an oversized log must be rotated, not grown (%d)" % size


print_failures = "§2 dead process fails fast, log stays bounded: OK"


def _check_origin_grant(tmp: Path) -> None:
    grant = ShareGrant("tunnel")
    origin_file = tmp / ".tunnel-origin"

    # The guard reads this file per request, so publishing it is the whole
    # grant — no app restart, and the trailing slash must not survive or the
    # string comparison against the browser's Origin header fails.
    grant.publish(tmp, URL + "/")
    assert origin_file.read_text(encoding="utf-8").strip() == URL, "bad origin file"

    # The origin grant authenticates nobody; the share secret does. It is
    # minted with the grant, survives a re-publish of the same tunnel (links
    # already sent keep working), and dies with it.
    secret_file = tmp / ".tunnel-secret"
    secret = secret_file.read_text(encoding="utf-8").strip()
    assert len(secret) >= 32, "share secret must be minted with the grant"
    grant.publish(tmp, URL)
    assert secret_file.read_text(encoding="utf-8").strip() == secret
    assert grant.link(tmp) == f"{URL}/?a2app_share={secret}"

    grant.revoke(tmp)
    assert not origin_file.exists(), "stopping the tunnel must revoke the grant"
    assert not secret_file.exists(), "stopping the tunnel must end every session"
    assert grant.link(tmp) is None, "no grant, no link"
    grant.revoke(tmp)  # idempotent: closing runs often

    # A new tunnel is a new secret: old links must not reopen it.
    grant.publish(tmp, URL)
    assert secret_file.read_text(encoding="utf-8").strip() != secret


print_origin = "§3 shared origin + share secret published and revoked: OK"


def _check_serving_port(tmp: Path) -> None:
    """Sharing must aim at the port the app binds, not the one merely reserved.

    Live case: port=3100 (PocketBase listening, serving edits), backend_port=
    3101 (allocated, bound by nothing). Sharing preferred backend_port, so the
    tunnel came up healthy and then answered every visitor with a refused
    connection. Nothing binds backend_port any more, so there is no fallback.
    """
    project = AgentAppProject(id="p", name="T", description="", path=str(tmp))
    project.port, project.backend_port = 3100, 3101
    assert AgentAppManager._serving_port(project) == 3100, (
        "must follow runner.start's port"
    )

    project.port = None
    assert AgentAppManager._serving_port(project) is None, (
        "never the unbound backend_port"
    )


print_port = "§5 sharing targets the bound port, not the reserved one: OK"


def _check_external_guard(tmp: Path) -> None:
    """External apps enforce the same policy in Python, so it must move too —
    otherwise sharing works for native apps and silently 403s for external."""
    proxy = ExternalA2AppProxy.__new__(ExternalA2AppProxy)
    proxy.project_dir = tmp

    assert proxy._origin_allowed("http://127.0.0.1:3101")
    assert proxy._origin_allowed("http://localhost:3101")
    assert not proxy._origin_allowed(URL), "no tunnel = loopback only"

    (tmp / ".tunnel-origin").write_text(URL + "\n", encoding="utf-8")
    assert proxy._origin_allowed(URL), "published origin must be honoured"
    assert not proxy._origin_allowed("https://someone-else.trycloudflare.com"), (
        "the grant is one exact origin, not every tunnel"
    )

    (tmp / ".tunnel-origin").unlink()
    assert not proxy._origin_allowed(URL), "revocation must take effect at once"


print_external = "§4 external-app proxy honours the same grant: OK"


async def _check_tunnel_needs_token(tmp: Path) -> None:
    """A failed token mint (launch only warns) + "share this app" used to be
    a publicly writable app. Opening a channel refuses, before touching
    anything — including a share that is already open."""
    channel, project, _ = _fixture(tmp)
    closed = []

    async def _close(p):
        closed.append(p.id)

    channel.close = _close
    token_file = tmp / ".agent-token"
    for content in (None, "", "  \n"):
        if content is None:
            token_file.unlink(missing_ok=True)
        else:
            token_file.write_text(content, encoding="utf-8")
        try:
            await channel.open(project, 3101)
        except ShareError as e:
            assert "access token" in str(e), e
        else:
            raise AssertionError(f"shared without a token ({content!r})")
    assert not closed, "refused before touching any existing share"
    assert not (tmp / ".tunnel-secret").exists()
    assert not (tmp / ".tunnel-origin").exists()


print_needs_token = "§4b tunnel refuses to share an app with no agent token: OK"


async def _check_never_a_dead_link(tmp: Path) -> None:
    """A tunnel that never came up must be an error to the owner, never a
    link: whatever cloudflared prints, and however long it stays alive."""
    channel, project, fake = _fixture(tmp)
    handle, log_path = channel._open_log(project, 3101)
    metrics = f"127.0.0.1:{channel._free_loopback_port()}"

    proc = subprocess.Popen(
        [sys.executable, "-c", FAILED_REQUEST], stdout=handle, stderr=subprocess.STDOUT
    )
    url = await channel._await_ready(proc, metrics, log_path, timeout=20)
    channel._close_log(handle)
    assert url is None, f"a failed quick-tunnel request was handed out as {url}"
    assert "api.trycloudflare.com" in log_path.read_text(encoding="utf-8")

    # Up and named, but not connected to Cloudflare: not a link either.
    proc = subprocess.Popen(
        [sys.executable, str(fake), "--metrics", metrics, "--never-ready"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = await channel._await_ready(proc, metrics, log_path, timeout=3)
    finally:
        proc.kill()
        proc.wait()
    assert url is None, f"an unconnected tunnel was handed out as {url}"


print_dead_link = "§6 a tunnel that never came up is an error, never a link: OK"


async def _check_delayed_readiness(tmp: Path) -> None:
    """Edge retries can take over 30 seconds, even across a clock change."""
    from aiohttp import web

    # Advance only the sharing deadline's clock: real HTTP requests still
    # exercise both endpoints without making this regression take 35 seconds.
    for jump_wall_clock in (False, True):
        elapsed = [0.0]
        wall_offset = [0.0]
        statuses = []
        hostname_requests = []

        async def ready(request):
            elapsed[0] = min(elapsed[0] + 10, 35)
            if jump_wall_clock:
                wall_offset[0] = 86400
            status = 200 if elapsed[0] >= 35 else 503
            statuses.append(status)
            return web.json_response({"status": status}, status=status)

        async def quicktunnel(request):
            hostname_requests.append(request.path)
            return web.json_response(
                {"hostname": "fake-tunnel-for-tests.trycloudflare.com"}
            )

        app = web.Application()
        app.router.add_get("/ready", ready)
        app.router.add_get("/quicktunnel", quicktunnel)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            clock = SimpleNamespace(
                monotonic=lambda: elapsed[0],
                time=lambda: elapsed[0] + wall_offset[0],
            )
            proc = SimpleNamespace(poll=lambda: None)
            with patch("app.agent_app.sharing.time", clock):
                url = await TunnelChannel._await_ready(
                    proc, f"127.0.0.1:{port}", tmp / "delayed.log"
                )
            assert url == URL, (
                f"delayed tunnel failed (clock jump={jump_wall_clock}): {url}"
            )
            assert statuses == [503, 503, 503, 200], statuses
            assert hostname_requests == ["/quicktunnel"], hostname_requests
        finally:
            await runner.cleanup()


print_delayed = (
    "§7 readiness after 35s survives edge retries and wall-clock changes: OK"
)


with tempfile.TemporaryDirectory() as _tmp:
    asyncio.run(_check_sink(Path(_tmp)))
    print(print_sink)

with tempfile.TemporaryDirectory() as _tmp:
    asyncio.run(_check_failure_paths(Path(_tmp)))
    print(print_failures)

with tempfile.TemporaryDirectory() as _tmp:
    _check_origin_grant(Path(_tmp))
    print(print_origin)

with tempfile.TemporaryDirectory() as _tmp:
    _check_external_guard(Path(_tmp))
    print(print_external)

with tempfile.TemporaryDirectory() as _tmp:
    asyncio.run(_check_tunnel_needs_token(Path(_tmp)))
    print(print_needs_token)

with tempfile.TemporaryDirectory() as _tmp:
    _check_serving_port(Path(_tmp))
    print(print_port)

with tempfile.TemporaryDirectory() as _tmp:
    asyncio.run(_check_never_a_dead_link(Path(_tmp)))
    print(print_dead_link)

with tempfile.TemporaryDirectory() as _tmp:
    asyncio.run(_check_delayed_readiness(Path(_tmp)))
    print(print_delayed)

print("tunnel: all checks OK")
