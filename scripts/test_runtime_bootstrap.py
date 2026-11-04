"""Online smoke test of runtime setup in an isolated, tool-free installation.

Copies only source (no node_modules/runtimes), downloads the pinned runtimes,
prepares Agent Apps, and verifies a second run reuses the installation. Does
not install the Python application packages or register/start the service.
"""

import os
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download-cache",
        type=Path,
        help="Optional verified runtime archive cache for slow test hosts",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="CraftBot setup caf\u00e9 ") as temporary:
        root = Path(temporary)
        app = root / "app"
        app.mkdir()
        for name in (
            "__init__.py",
            "paths.py",
            "downloads.py",
            "node_runtime.py",
            "runtime_manifest.py",
            "runtime-manifest.json",
        ):
            shutil.copy2(ROOT / "app" / name, app / name)
        shutil.copytree(
            ROOT / "app/provision",
            app / "provision",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copytree(
            ROOT / "agent-app",
            root / "agent-app",
            ignore=shutil.ignore_patterns(
                "node_modules", "examples", "dist", "__pycache__"
            ),
        )
        (root / "agent-app/examples").mkdir()
        (root / ".craftbot-managed").touch()
        # Exercise the shipped code under a fresh source layout and user-data root.
        worker = r"""
import os, subprocess, socket, time, urllib.request
from app import node_runtime
from app.provision import Context
from app.provision.pipeline import run
from app.provision.runtimes import PythonStage, NodeStage
from app.provision.deps import AgentAppToolsStage, PocketBaseStage
ctx = Context(os.getcwd(), os.environ['CRAFTBOT_HOME'])
stages = [PythonStage(), NodeStage(), AgentAppToolsStage(), PocketBaseStage()]
# Force bootstrap even when the test harness happens to be Python 3.10.
result = stages[0].apply(ctx, print)
assert result.ok, result
report = run(stages, ctx, print)
assert report.ok, report.to_dict()
node = node_runtime.node_cmd()
cli = os.path.join(ctx.code_root, 'agent-app/tools/src/cli.ts')
subprocess.run([node, cli, 'create', 'Bootstrap smoke', '--dir', os.environ['CRAFTBOT_TEST_APPS'], '--port', '18090'], env=node_runtime.child_env(), check=True)
project = os.path.join(os.environ['CRAFTBOT_TEST_APPS'], 'bootstrap-smoke')
subprocess.run(node_runtime.npm_command() + ['install', '--ignore-scripts', '--no-audit', '--no-fund'],
               cwd=os.path.join(project, 'frontend'), env=node_runtime.child_env(), check=True)
subprocess.run([node, cli, 'validate', project], env=node_runtime.child_env(), check=True)
binary = subprocess.check_output([node, cli, 'pb', 'path'], env=node_runtime.child_env(), text=True).strip().splitlines()[-1]
with socket.socket() as reservation:
    reservation.bind(('127.0.0.1', 0))
    port = reservation.getsockname()[1]
server = subprocess.Popen([binary, 'serve', f'--http=127.0.0.1:{port}', '--dir', os.path.join(project, 'pb/pb_data'),
                           '--hooksDir', os.path.join(project, 'pb/pb_hooks'), '--publicDir', os.path.join(project, 'pb/pb_public')],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for attempt in range(60):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
                assert response.status == 200
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                assert b'<html' in response.read().lower()
            break
        except OSError:
            if server.poll() is not None or attempt == 59:
                raise RuntimeError('Scaffolded app did not become healthy')
            time.sleep(0.5)
finally:
    server.terminate()
    server.wait(timeout=15)
# Re-check without applying anything: all required runtimes must already work.
report = run(stages, ctx, print, check_only=True)
assert report.ok, report.to_dict()
print('RUNTIME BOOTSTRAP PASS: private Python, Node/npm, tooling, PocketBase, scaffold/build/serve, reuse')
"""
        env = os.environ.copy()
        for key in (
            "CRAFTBOT_PYTHON",
            "CRAFTBOT_NODE",
            "NVM_HOME",
            "NVM_DIR",
            "CRAFTBOT_DOWNLOAD_CACHE",
            "NODE_PATH",
            "NODE_OPTIONS",
        ):
            env.pop(key, None)
        env.update(
            {
                "PATH": str(root / "no-tools"),
                "PYTHONPATH": str(root),
                "PYTHONUTF8": "1",
                "CRAFTBOT_HOME": str(root / "state"),
                "AGENT_APP_PB_CACHE": str(root / "pb-cache"),
                "CRAFTBOT_TEST_APPS": str(root / "apps"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        if args.download_cache:
            env["CRAFTBOT_DOWNLOAD_CACHE"] = str(args.download_cache.resolve())
        return subprocess.run(
            [sys.executable, "-u", "-c", worker], cwd=root, env=env
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
