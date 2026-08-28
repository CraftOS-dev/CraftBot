"""Tunnel sharing: the output sink and the shared-origin grant.

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

Run:  python -m app.living_ui.test_tunnel

Style follows app/living_ui/test_data_safety.py: a module-level assert
script with hand-rolled stubs, no pytest.
"""

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows consoles default to cp1252; the checks print arrows and dashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.living_ui.a2app_proxy import ExternalA2AppProxy
from app.living_ui.manager import LivingUIManager, LivingUIProject

# A stand-in for cloudflared: the real banner shape, then far more chatter
# than any pipe buffer holds. This is the exact shape that used to wedge.
FAKE_CLOUDFLARED = r'''
import sys
sys.stderr.write("INF Requesting new quick Tunnel on trycloudflare.com...\n")
sys.stderr.write("+" + "-" * 60 + "+\n")
sys.stderr.write("|  https://fake-tunnel-for-tests.trycloudflare.com  |\n")
sys.stderr.write("+" + "-" * 60 + "+\n")
sys.stderr.flush()
for i in range(4000):
    sys.stderr.write("INF served request %d %s\n" % (i, "x" * 60))
sys.stderr.write("DONE\n")
'''

URL = "https://fake-tunnel-for-tests.trycloudflare.com"


def _fixture(tmp: Path) -> "tuple[LivingUIManager, LivingUIProject, Path]":
    """A manager with no state of its own — these paths never touch it."""
    (tmp / "logs").mkdir(exist_ok=True)
    fake = tmp / "fake_cloudflared.py"
    fake.write_text(FAKE_CLOUDFLARED, encoding="utf-8")
    mgr = LivingUIManager.__new__(LivingUIManager)
    project = LivingUIProject(id="testproj", name="T", description="", path=str(tmp))
    return mgr, project, fake


async def _check_sink(tmp: Path) -> None:
    mgr, project, fake = _fixture(tmp)

    handle, log_path, offset = mgr._open_tunnel_log(project, 3101)
    assert handle is not None, "no sink means no URL and no log"
    assert log_path == tmp / "logs" / "cloudflared.log", log_path

    proc = subprocess.Popen(
        [sys.executable, str(fake)], stdout=handle, stderr=subprocess.STDOUT
    )
    url = await mgr._parse_cloudflare_url(proc, log_path, offset, timeout=20)
    assert url == URL, url

    # THE regression: the child must run to completion, not block on output.
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("cloudflared blocked on its output — deadlock is back")
    mgr._close_tunnel_log(handle)

    body = log_path.read_text(encoding="utf-8", errors="replace")
    assert "=== cloudflared start" in body, "session header missing"
    assert body.rstrip().endswith("DONE"), "log truncated: tail=%r" % body[-80:]
    assert len(body) > 300_000, "only %d bytes captured" % len(body)
print_sink = "§1 cloudflared output is captured, never buffered: OK"


async def _check_failure_paths(tmp: Path) -> None:
    mgr, project, _ = _fixture(tmp)

    # A cloudflared that dies without announcing must fail fast, not sit out
    # the whole timeout — the launch path is awaiting this.
    dead = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    dead.wait()
    url = await mgr._parse_cloudflare_url(dead, tmp / "absent.log", 0, timeout=30)
    assert url is None, url

    # The log is append-mode across restarts, but capped.
    log_path = mgr._tunnel_log_path(project)
    log_path.write_text("y" * 2_500_000, encoding="utf-8")
    handle, _, offset = mgr._open_tunnel_log(project, 3101)
    mgr._close_tunnel_log(handle)
    assert offset < 1000, "an oversized log must be rotated, not grown (%d)" % offset
print_failures = "§2 dead process fails fast, log stays bounded: OK"


def _check_origin_grant(tmp: Path) -> None:
    mgr, project, _ = _fixture(tmp)
    origin_file = tmp / ".tunnel-origin"

    # The guard reads this file per request, so publishing it is the whole
    # grant — no app restart, and the trailing slash must not survive or the
    # string comparison against the browser's Origin header fails.
    mgr._publish_tunnel_origin(project, URL + "/")
    assert origin_file.read_text(encoding="utf-8").strip() == URL, "bad origin file"

    mgr._publish_tunnel_origin(project, None)
    assert not origin_file.exists(), "stopping the tunnel must revoke the grant"
    mgr._publish_tunnel_origin(project, None)  # idempotent: stop_tunnel runs often
print_origin = "§3 shared origin published and revoked: OK"


def _check_serving_port(tmp: Path) -> None:
    """Sharing must aim at the port the app binds, not the one merely reserved.

    Live case: port=3100 (PocketBase listening, serving edits), backend_port=
    3101 (allocated, bound by nothing). Sharing preferred backend_port, so the
    tunnel came up healthy and then answered every visitor with a refused
    connection.
    """
    mgr, project, _ = _fixture(tmp)
    project.port, project.backend_port = 3100, 3101
    assert mgr._serving_port(project) == 3100, "must follow runner.start's port"

    project.port = None
    assert mgr._serving_port(project) == 3101, "fall back, don't return None"

    project.backend_port = None
    assert mgr._serving_port(project) is None
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
    _check_serving_port(Path(_tmp))
    print(print_port)

print("tunnel: all checks OK")
