"""Exercise production SPA routing without bootstrapping the user's runtime."""

import ast
import os
from pathlib import Path
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def frontend(tmp_path):
    source = Path(__file__).resolve().parents[1] / "run.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_launch_static_frontend"
    )
    # Importing run.py bootstraps state. Compile its real server function alone.
    function.returns = None
    namespace = {
        "os": os,
        "FRONTEND_DIR": str(tmp_path),
        "FRONTEND_PORT": 0,
        "BACKEND_PORT": 0,
        "_background_processes": [],
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>CraftBot test shell</h1>", encoding="utf-8")
    (dist / "assets" / "main.js").write_text("// test asset", encoding="utf-8")
    server = namespace["_launch_static_frontend"](silent=True)
    assert server is not None
    try:
        yield f"http://127.0.0.1:{server._server.server_port}"
    finally:
        server.terminate()
        server._server.server_close()


@pytest.mark.parametrize(
    "route,status,body",
    [
        ("/", 200, "CraftBot test shell"),
        ("/session/qa", 200, "CraftBot test shell"),
        (
            "/settings?tab=agent_app&path=C%3A%2FUsers%2Fqa%2F.a2app%2Fapps%2Fnotes&id=qa",
            200,
            "CraftBot test shell",
        ),
        ("/assets/main.js?v=1.0", 200, "// test asset"),
        ("/assets/missing.js?path=.a2app", 404, "File not found"),
    ],
)
def test_production_routes_and_assets(frontend, route, status, body):
    try:
        response = urllib.request.urlopen(frontend + route, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == status
        assert body in response.read().decode("utf-8")
