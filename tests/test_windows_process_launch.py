"""Exercise hidden process trees through CraftBot's Python action launchers."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from agent_core.core.impl.action import executor
from agent_core.core.impl.mcp.server import StdioTransport
from agent_core.utils import windows_process

PROBE = Path(__file__).parent / "windows_shell" / "console_probe.py"
CODE = """
def probe(input_data):
    import json, subprocess, sys
    output = subprocess.check_output([sys.executable, input_data['probe'], '2', '-'], text=True)
    return {'status':'success', 'records':[json.loads(line) for line in output.splitlines()]}
"""


def assert_hidden(records):
    assert len(records) == 3
    assert all(r["console"] and not r["visible"] for r in records), records
    assert len({r["console"] for r in records}) == 1, records


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows console visibility")
@pytest.mark.parametrize("mode", ["internal", "sandboxed"])
def test_action_interpreter_and_its_descendants_stay_hidden(monkeypatch, mode):
    if mode == "internal":
        result = executor._atomic_action_internal_subprocess(
            CODE, {"probe": str(PROBE)}, sys.executable, timeout=15
        )
    else:
        # Exercise the real subprocess transport without touching the user's
        # persistent sandbox or fetching packages from the network.
        monkeypatch.setattr(
            executor, "_ensure_persistent_venv", lambda: Path(sys.executable)
        )
        result = executor._atomic_action_venv_process(
            CODE, {"probe": str(PROBE)}, 15, "CLI", []
        )
        assert result["returncode"] == 0, result
        result = json.loads(result["stdout"])
    assert result["status"] == "success", result
    assert_hidden(result["records"])


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows console visibility")
def test_venv_helper_interpreter_is_hidden(tmp_path):
    # The same invocation path runs ensurepip during sandbox creation. A
    # harmless probe checks it without installing anything into a live env.
    builder = executor._HiddenEnvBuilder(with_pip=False)
    builder.create(tmp_path / "venv")
    context = builder.ensure_directories(str(tmp_path / "venv"))
    output = tmp_path / "console.jsonl"
    builder._call_new_python(context, str(PROBE), "2", str(output))
    assert_hidden([json.loads(line) for line in output.read_text().splitlines()])


def test_non_windows_launch_options_are_unchanged(monkeypatch):
    monkeypatch.setattr(windows_process.sys, "platform", "linux")
    assert windows_process.hidden_console_kwargs(new_process_group=True) == {}


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows console visibility")
@pytest.mark.parametrize("batch_wrapper", [False, True])
def test_stdio_mcp_and_descendants_stay_hidden(tmp_path, batch_wrapper):
    server = tmp_path / "stdio_server.py"
    server.write_text(
        """
import json, os, subprocess, sys

for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    result = {}
    if request['method'] == 'probe':
        output = subprocess.check_output(
            [sys.executable, os.environ['CRAFTBOT_TEST_PROBE'], '2', '-'], text=True
        )
        result = {'records': [json.loads(line) for line in output.splitlines()],
                  'params': request['params']}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
    if request['method'] == 'shutdown':
        break
""",
        encoding="utf-8",
    )
    if batch_wrapper:
        # npx/uvx-style wrappers must remain hidden too, including their children.
        wrapper = tmp_path / "stdio_server.cmd"
        wrapper.write_text(
            '@echo off\n"%CRAFTBOT_TEST_PYTHON%" "%~dp0stdio_server.py"\n'
        )
        command, args = str(wrapper), []
    else:
        command, args = sys.executable, [str(server)]

    async def exercise():
        transport = StdioTransport(
            command,
            args,
            {"CRAFTBOT_TEST_PROBE": str(PROBE), "CRAFTBOT_TEST_PYTHON": sys.executable},
            cwd=str(tmp_path),
        )
        try:
            assert await transport.connect()
            params = {"text": "stdio still works"}
            reply = await transport.send_request("probe", params)
            assert reply["result"]["params"] == params
            assert_hidden(reply["result"]["records"])
        finally:
            if transport.is_connected:
                await transport.send_request("shutdown")
                await asyncio.wait_for(transport._process.wait(), timeout=5)
            await transport.disconnect()
        assert not transport.is_connected

    asyncio.run(exercise())
