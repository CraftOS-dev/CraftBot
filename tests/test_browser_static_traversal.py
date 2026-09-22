"""Path traversal through the browser adapter's dist/ catch-all route.

Runs the production handler (_make_static_or_spa) on a real aiohttp server and
sends raw request lines over a socket, so no client normalizes the path first.
"""

import asyncio
import socket
import sys
import threading
from pathlib import Path

import pytest
from aiohttp import web

from app.ui_layer.adapters.browser_adapter import _make_static_or_spa

SECRET = "SECRET_API_KEY=sk-test-leak"
INDEX = "<!doctype html>INDEX"


def _can_symlink(tmp: Path) -> bool:
    probe = tmp / "_symlink_probe"
    try:
        probe.symlink_to(tmp)
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("traversal")
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "中文").mkdir()
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    (dist / "日本語.txt").write_text("japanese-ok", encoding="utf-8")
    (dist / "中文" / "图片.txt").write_text("chinese-ok", encoding="utf-8")
    (root / ".env").write_text(SECRET, encoding="utf-8")
    # A sibling whose name starts with "dist" catches string-prefix checks.
    (root / "dist-evil").mkdir()
    (root / "dist-evil" / "leak.txt").write_text(SECRET, encoding="utf-8")

    symlinks = _can_symlink(root)
    if symlinks:
        (dist / "escape.txt").symlink_to(root / ".env")
        (dist / "escape_dir").symlink_to(root, target_is_directory=True)
        (dist / "alias.js").symlink_to(dist / "assets" / "app.js")
    junction = False
    if not symlinks and sys.platform == "win32":
        # Junctions need no privilege and resolve() follows them like symlinks.
        import _winapi

        _winapi.CreateJunction(str(root), str(dist / "escape_junction"))
        junction = True

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state = {}

    async def start():
        app = web.Application()
        app.router.add_get("/{path:.*}", _make_static_or_spa(dist))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        state["runner"] = runner
        state["port"] = site._server.sockets[0].getsockname()[1]
        ready.set()

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    asyncio.run_coroutine_threadsafe(start(), loop)
    assert ready.wait(10)

    yield {"port": state["port"], "root": root, "symlinks": symlinks, "junction": junction}

    asyncio.run_coroutine_threadsafe(state["runner"].cleanup(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(10)


def _get(server, target: str):
    """Send `GET <target>` verbatim; return (status, body)."""
    with socket.create_connection(("127.0.0.1", server["port"]), timeout=10) as s:
        s.sendall(
            b"GET " + target.encode("utf-8") + b" HTTP/1.1\r\n"
            b"Host: localhost\r\nConnection: close\r\n\r\n"
        )
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, body.decode("utf-8", errors="replace")


def _assert_refused(server, target: str):
    status, body = _get(server, target)
    assert "sk-test-leak" not in body, f"{target} leaked the secret"
    assert status == 404, f"{target} -> {status}"


# ── Traversal: must be refused ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "target",
    [
        "/../.env",
        "/assets/../../.env",
        "/%2e%2e/.env",
        "/%2e%2e%2f.env",
        "/%2E%2E%2F.env",
        "/assets%2f%2e%2e%2f%2e%2e%2f.env",
        "/../dist-evil/leak.txt",
        "/a%00b",
    ],
)
def test_relative_traversal_refused(server, target):
    _assert_refused(server, target)


@pytest.mark.parametrize(
    "target", ["/..%5c.env", "/..\\.env", "/assets\\..\\..\\.env"]
)
def test_backslash_traversal_refused(server, target):
    if sys.platform == "win32":
        _assert_refused(server, target)
    else:
        # "\" is an ordinary filename character on POSIX: a missing file in dist/.
        assert _get(server, target) == (200, INDEX)


def test_absolute_windows_paths_refused(server):
    secret = server["root"] / ".env"
    _assert_refused(server, "/" + secret.as_posix())  # /C:/Users/.../.env
    _assert_refused(server, "/" + str(secret).replace("\\", "%5c"))
    _assert_refused(server, "/C:%5cWindows%5cwin.ini")
    _assert_refused(server, "/C:\\Windows\\win.ini")
    _assert_refused(server, "/C:win.ini")  # drive-relative


def test_absolute_posix_and_unc_paths_refused(server):
    _assert_refused(server, "//etc/passwd")
    _assert_refused(server, "/%2fetc%2fpasswd")
    _assert_refused(server, "/%5cetc%5cpasswd")
    _assert_refused(server, "//attacker.invalid/share/x")
    _assert_refused(server, "/%5c%5cattacker.invalid%5cshare%5cx")


def test_double_encoded_is_not_decoded_twice(server):
    status, body = _get(server, "/%252e%252e%252f.env")
    assert status == 200 and body == INDEX


def test_symlinks_out_of_dist_refused(server):
    if not server["symlinks"]:
        pytest.skip("symlink creation not permitted (Windows needs Developer Mode)")
    _assert_refused(server, "/escape.txt")
    _assert_refused(server, "/escape_dir/.env")


def test_junction_out_of_dist_refused(server):
    if not server["junction"]:
        pytest.skip("junction fallback only used on Windows without symlink privilege")
    _assert_refused(server, "/escape_junction/.env")
    _assert_refused(server, "/escape_junction/dist-evil/leak.txt")


def test_symlink_inside_dist_served(server):
    if not server["symlinks"]:
        pytest.skip("symlink creation not permitted (Windows needs Developer Mode)")
    assert _get(server, "/alias.js") == (200, "console.log('app')")


# ── Legitimate requests: must still work ────────────────────────────────────


def test_normal_asset_served(server):
    assert _get(server, "/assets/app.js") == (200, "console.log('app')")


def test_root_file_served(server):
    assert _get(server, "/index.html") == (200, INDEX)


@pytest.mark.parametrize(
    "target, body",
    [
        ("/%E6%97%A5%E6%9C%AC%E8%AA%9E.txt", "japanese-ok"),
        ("/%E4%B8%AD%E6%96%87/%E5%9B%BE%E7%89%87.txt", "chinese-ok"),
    ],
)
def test_non_ascii_filenames_served(server, target, body):
    # Browsers percent-encode UTF-8; aiohttp rejects raw non-ASCII request lines.
    assert _get(server, target) == (200, body)


@pytest.mark.parametrize(
    "target",
    ["/", "/chat", "/chat/123", "/settings/profile?tab=a", "/assets", "/%E4%B8%AD%E6%96%87"],
)
def test_spa_routes_fall_back_to_index(server, target):
    assert _get(server, target) == (200, INDEX)
