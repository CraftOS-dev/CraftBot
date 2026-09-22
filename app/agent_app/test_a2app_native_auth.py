"""Native (PocketBase) adapter caller auth, against the real blueprint hooks.

The bypass this pins: `_system.pb.js`'s token guard ran only when there was
NO Origin header, so any request carrying an allowed one — loopback, or the
shared tunnel origin — wrote without a credential. Tunnel traffic reaches the
app over loopback and can send any Origin it likes, so a shared app was
writable by anyone with the URL. Origin and caller are now independent checks
(_a2app_lib.js authorizeCaller, rule-for-rule with a2app_proxy.guard_request,
whose matrix lives in test_a2app_external.py).

Boots the pinned PocketBase on the blueprint's own pb_hooks — the system hooks
are the unit under test, so nothing is stubbed. SKIPPED if the binary is not
in the tooling cache.

Run:  python -m app.agent_app.test_a2app_native_auth

Style follows test_data_safety.py: a module-level assert script, no pytest.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
BLUEPRINT = REPO / "agent-app" / "blueprint"
TOKEN = "native-test-agent-token"
SHARED = "https://shared-demo.trycloudflare.com"
SECRET = "native-share-secret-0123456789abcdef"
VIA_TUNNEL = {
    "Host": "shared-demo.trycloudflare.com",
    "Cf-Ray": "8c0ffee-LHR",
    "Cf-Connecting-Ip": "203.0.113.9",
    "X-Forwarded-For": "203.0.113.9",
}
# The blueprint migration's rules are scaffold placeholders; authMode "none"
# renders them open, which is exactly the posture the token guard protects.
MIGRATION = """/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const c = new Collection({
    type: 'base', name: 'items',
    listRule: '', viewRule: '', createRule: '', updateRule: '', deleteRule: '',
    fields: [{ name: 'title', type: 'text', required: true, max: 200 },
             { name: 'done', type: 'bool' }],
  });
  app.save(c);
}, (app) => { app.delete(app.findCollectionByNameOrId('items')); });
"""


def _pinned_pb_binary() -> Path:
    version = (REPO / "agent-app" / "spec" / "pocketbase.version").read_text(
        encoding="utf-8"
    ).strip()
    cache = os.environ.get("AGENT_APP_PB_CACHE")
    if cache:
        root = Path(cache)
    elif os.name == "nt":
        root = Path(os.environ["LOCALAPPDATA"]) / "craftos-agent-app" / "pb"
    else:
        root = Path.home() / ".cache" / "craftos-agent-app" / "pb"
    return root / version / ("pocketbase.exe" if os.name == "nt" else "pocketbase")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _req(base, method, path, headers=None, body=None, cookie=None):
    """(status, headers, json-or-text). Never follows redirects."""
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    if cookie:
        h["Cookie"] = f"{cookie[0]}={cookie[1]}"
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        resp = _opener.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        resp = e
    raw = resp.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = raw
    return resp.status if hasattr(resp, "status") else resp.code, resp.headers, payload


def _session_cookie(headers):
    for raw in headers.get_all("Set-Cookie") or []:
        pair = raw.split(";", 1)[0]
        if pair.startswith("a2app_s_"):
            name, _, value = pair.partition("=")
            return name, value, raw
    return None


def _suite(base: str, proj: Path, superuser) -> None:
    create = "/api/collections/items/records"
    loopback = {"Origin": base}

    def post(headers, cookie=None, title="x", path=create):
        body = {"title": title} if path == create else {}
        return _req(base, "POST", path, headers, body, cookie)[0]

    def count():
        _, _, page = _req(base, "GET", create + "?perPage=1")
        return page["totalItems"]

    before = count()

    # ── refused: Origin is never a credential ──
    assert post({"Origin": "https://evil.example"}) == 403
    for label, headers in (
        ("no Origin, no token", {}),
        ("no Origin, wrong token", {"X-A2App-Token": "nope"}),
        ("loopback Origin, no token", loopback),
        ("other loopback port, no token", {"Origin": "http://localhost:1"}),
        ("loopback Origin, wrong token", {**loopback, "X-A2App-Token": "nope"}),
    ):
        assert post(headers) == 401, label
    assert post(loopback, path="/api/ops/items/clear-done") == 401, "ops route too"
    assert count() == before, "a refused write landed"

    # ── the agent ──
    assert post({"X-A2App-Token": TOKEN}) == 200
    assert post({**loopback, "X-A2App-Token": TOKEN}) == 200
    assert post({"X-A2App-Token": TOKEN}, path="/api/ops/items/clear-done") == 200

    # ── signed-in principal (multi-user apps' frontends) ──
    _, _, auth = _req(
        base,
        "POST",
        "/api/collections/_superusers/auth-with-password",
        {},
        {"identity": superuser[0], "password": superuser[1]},
    )
    assert post({**loopback, "Authorization": auth["token"]}) == 200

    # ── the app's own UI, locally: the SPA entry issues the session ──
    status, headers, _ = _req(base, "GET", "/")
    assert status == 200
    local = _session_cookie(headers)
    assert local, "the page that boots the UI must hand it a session"
    assert "HttpOnly" in local[2] and "SameSite=Lax" in local[2]
    assert "Secure" not in local[2]
    local = local[:2]
    _, headers, _ = _req(base, "GET", "/", cookie=local)
    assert _session_cookie(headers) is None, "valid session not re-issued"
    _, headers, _ = _req(base, "GET", "/api/health")
    assert _session_cookie(headers) is None, "API responses mint nothing"
    assert post(loopback, cookie=local) == 200
    assert post(loopback, cookie=(local[0], local[1][:-1] + "0")) == 401

    # ── through the tunnel ──
    (proj / ".tunnel-origin").write_text(SHARED, encoding="utf-8")
    assert post({"Origin": SHARED}) == 401, "shared Origin alone, no token"
    assert post({"Origin": SHARED, "X-A2App-Token": "nope"}) == 401
    status, _, body = _req(base, "GET", create, VIA_TUNNEL)
    assert status == 401 and body["code"] == "share_session_required", body
    assert _req(base, "GET", "/", VIA_TUNNEL)[0] == 401, "the UI itself is gated"
    # Either signal alone marks the tunnel: a public Host (request.host in Go,
    # not the header map) or a Cloudflare stamp on a loopback Host.
    assert _req(base, "GET", create, {"Host": "shared-demo.trycloudflare.com"})[0] == 401
    assert _req(base, "GET", create, {"Cf-Ray": "8c0ffee-LHR"})[0] == 401
    assert post({**VIA_TUNNEL, **loopback}) == 401, "forged loopback Origin"
    assert post({**VIA_TUNNEL, "Origin": SHARED}, cookie=local) == 401

    (proj / ".tunnel-secret").write_text(SECRET, encoding="utf-8")
    status, _, body = _req(base, "GET", "/?a2app_share=wrong", VIA_TUNNEL)
    assert status == 403 and body["code"] == "share_link_invalid"
    status, headers, _ = _req(base, "GET", f"/?a2app_share={SECRET}&tab=2", VIA_TUNNEL)
    assert status == 302, status
    assert headers["Location"] == "/?tab=2", headers["Location"]
    shared = _session_cookie(headers)
    assert shared and "Secure" in shared[2]
    shared = shared[:2]

    assert _req(base, "GET", "/", VIA_TUNNEL, cookie=shared)[0] == 200
    assert _req(base, "GET", create, VIA_TUNNEL, cookie=shared)[0] == 200
    assert post({**VIA_TUNNEL, "Origin": SHARED}, cookie=shared) == 200
    assert post(loopback, cookie=shared) == 401, "tunnel session is not local"
    assert post({**VIA_TUNNEL, "X-A2App-Token": TOKEN}) == 200
    assert post({**VIA_TUNNEL, "Origin": "https://evil.example"}, cookie=shared) == 403

    (proj / ".tunnel-secret").unlink()
    (proj / ".tunnel-origin").unlink()
    assert post({**VIA_TUNNEL, "Origin": SHARED}, cookie=shared) in (401, 403)
    assert _req(base, "GET", create, VIA_TUNNEL, cookie=shared)[0] == 401

    # ── no agent token on disk: the tunnel fails CLOSED, local stays usable ──
    # (a failed mint at launch + "share this app" must never be public writes)
    token_file = proj / ".agent-token"
    token_file.write_text("", encoding="utf-8")
    try:
        status, _, body = _req(base, "POST", create, VIA_TUNNEL, {"title": "open?"})
        assert status == 503 and body["code"] == "share_unavailable", (status, body)
        assert _req(base, "DELETE", create + "/anything", VIA_TUNNEL)[0] == 503
        assert _req(base, "GET", create, VIA_TUNNEL)[0] == 503
        assert post(loopback, title="owner") == 200, "a missing token never locks the owner out"
    finally:
        token_file.write_text(TOKEN, encoding="utf-8")


def main() -> None:
    pb = _pinned_pb_binary()
    if not pb.exists():
        print(f"native caller auth: SKIPPED (no PocketBase at {pb})")
        return
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "app"
        shutil.copytree(BLUEPRINT / "pb" / "pb_hooks", proj / "pb" / "pb_hooks")
        (proj / "pb" / "pb_migrations").mkdir(parents=True)
        (proj / "pb" / "pb_migrations" / "1700000000_items.js").write_text(
            MIGRATION, encoding="utf-8"
        )
        (proj / "pb" / "pb_public").mkdir(parents=True)
        (proj / "pb" / "pb_public" / "index.html").write_text(
            "<!doctype html><title>app</title>", encoding="utf-8"
        )
        shutil.copy(BLUEPRINT / "operations.json", proj / "operations.json")
        (proj / "manifest.json").write_text(
            json.dumps({"id": "nativeauth", "authMode": "none"}), encoding="utf-8"
        )
        (proj / ".agent-token").write_text(TOKEN, encoding="utf-8")
        pb_data = proj / "pb" / "pb_data"
        superuser = ("agent@agent-app.local", "native-auth-password-123")
        subprocess.run(
            [str(pb), "superuser", "upsert", *superuser, "--dir", str(pb_data)],
            capture_output=True,
            timeout=120,
            check=True,
        )
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        proc = subprocess.Popen(
            [
                str(pb),
                "serve",
                f"--http=127.0.0.1:{port}",
                "--dir",
                str(pb_data),
                "--hooksDir",
                str(proj / "pb" / "pb_hooks"),
                "--migrationsDir",
                str(proj / "pb" / "pb_migrations"),
                "--publicDir",
                str(proj / "pb" / "pb_public"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(300):
                try:
                    urllib.request.urlopen(base + "/api/health", timeout=1)
                    break
                except Exception:
                    time.sleep(0.2)
            else:
                raise AssertionError("PocketBase never became healthy")
            _suite(base, proj, superuser)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
    print("native caller auth (blueprint hooks on real PocketBase): OK")


if __name__ == "__main__":
    main()
