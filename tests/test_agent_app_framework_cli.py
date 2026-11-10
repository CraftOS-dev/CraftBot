"""Real subprocess tests for CraftBot's transport, without installing an app.

Set CRAFTBOT_TEST_AGENT_APP_PACKAGE to an unchanged built CLI package to also
run the read-only upstream smoke test. The other cases use a disposable CLI.
"""

import asyncio
import json
import os
from pathlib import Path

import psutil
import pytest

from app import node_runtime
from app.agent_app import framework_cli
from app.agent_app.framework_cli import AgentAppCLI, FrameworkCLIUnavailable


FAKE_CLI = r"""
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { basename } from 'node:path';
const argv = process.argv.slice(2);
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
if (argv[0] === 'stream') {
  const event = Buffer.from('{"event":"step","step":"café","status":"start"}\r\n');
  const split = event.indexOf(Buffer.from('é')) + 1;
  process.stdout.write(event.subarray(0, split));
  await pause(25);
  process.stdout.write(event.subarray(split));
  process.stderr.write('diagnostic\n'.repeat(10000));
  const deadline = Date.now() + 10000;
  while (!existsSync(argv[1])) {
    if (Date.now() > deadline) throw new Error('test did not release the stream');
    await pause(10);
  }
  process.stdout.write('{"event":"result","ok":true}');
} else if (argv[0] === 'tree') {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    stdio: 'ignore', windowsHide: true,
  });
  console.log(JSON.stringify({ pid: process.pid, childPid: child.pid }));
  setInterval(() => {}, 1000);
} else if (argv[0] === 'flood') {
  console.log(JSON.stringify({ pid: process.pid }));
  setTimeout(() => process.stdout.write('x'.repeat(100000)), 100);
  setInterval(() => {}, 1000);
} else {
  process.stdout.write(JSON.stringify({
    binary: basename(process.argv[1]), argv, cwd: process.cwd(),
    home: process.env.A2APP_HOME, token: process.env.A2APP_TOKEN ?? null,
    marketplaceRef: process.env.A2APP_MARKETPLACE_REF,
    toolkits: process.env.A2APP_TOOLKITS_DIR ?? null,
  }, null, 2));
  process.stderr.write('diagnostic café\n');
  process.exitCode = Number(process.env.FAKE_EXIT_CODE ?? 0);
}
"""


@pytest.fixture
def cli(tmp_path):
    if node_runtime.resolve() is None:
        pytest.skip("CraftBot's Node runtime is required")
    package = tmp_path / "framework package"
    (package / "bin").mkdir(parents=True)
    (package / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    for name in ("agent-app", "a2app"):
        (package / "bin" / f"{name}.js").write_text(FAKE_CLI, encoding="utf-8")
    return AgentAppCLI(package, home=tmp_path / "framework home")


def running(process):
    return process.is_running() and process.status() != psutil.STATUS_ZOMBIE


@pytest.mark.parametrize("ref", ["main", "staging", "feature/pipeline"])
def test_cli_uses_the_marketplace_cards_branch(cli, tmp_path, monkeypatch, ref):
    monkeypatch.setattr("app.agent_app.marketplace_source.ref", lambda: ref)
    monkeypatch.setenv("A2APP_MARKETPLACE_REF", "stale-ambient-branch")
    result = asyncio.run(cli.run("agent-app", ["echo"], cwd=tmp_path))
    assert result.ok
    assert result.json()["marketplaceRef"] == ref


@pytest.mark.parametrize("override", [None, "explicit toolkits"])
def test_cli_passes_installed_toolkits_without_modifying_its_package(
    cli, tmp_path, monkeypatch, override
):
    configured = str(tmp_path / "marketplace toolkits")
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: configured)
    monkeypatch.delenv("A2APP_TOOLKITS_DIR", raising=False)
    if override:
        monkeypatch.setenv("A2APP_TOOLKITS_DIR", override)
    result = asyncio.run(cli.run("agent-app", ["echo"], cwd=tmp_path))
    assert result.ok
    assert result.json()["toolkits"] == (override or configured)


@pytest.fixture
def processes():
    """Remember only fixture-owned processes, including their creation identity."""
    owned = []
    yield owned
    for process in owned:
        try:
            if running(process):
                process.kill()
                process.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass


def remember(line, processes):
    message = json.loads(line)
    for key in ("pid", "childPid"):
        if key in message:
            processes.append(psutil.Process(message[key]))


async def assert_stopped(processes):
    deadline = asyncio.get_running_loop().time() + 5
    while any(running(process) for process in processes):
        assert asyncio.get_running_loop().time() < deadline, (
            "fixture process survived cleanup"
        )
        await asyncio.sleep(0.025)


@pytest.mark.parametrize("surface", ["agent-app", "a2app"])
def test_literal_arguments_explicit_binary_and_separate_output(cli, tmp_path, surface):
    cwd = tmp_path / "app café"
    cwd.mkdir()
    args = [
        "echo",
        "promote",
        '--title=x" & echo bad > injected.txt',
        "$(echo bad)",
        "line1\nline2",
        "",
    ]
    result = asyncio.run(cli.run(surface, args, cwd=cwd))
    assert result.ok
    assert result.json()["binary"] == f"{surface}.js"
    assert result.json()["argv"] == args
    assert Path(result.json()["cwd"]) == cwd
    assert result.stderr == "diagnostic café\n"
    assert not (cwd / "injected.txt").exists()


@pytest.mark.parametrize("code", [0, 1, 2, 3])
def test_preserves_cli_exit_codes(cli, tmp_path, code):
    result = asyncio.run(
        cli.run(
            "agent-app", ["echo"], cwd=tmp_path, env_extra={"FAKE_EXIT_CODE": str(code)}
        )
    )
    assert result.code == code
    assert result.ok is (code == 0)
    assert result.timed_out is False
    assert result.json() is not None  # JSON output alone does not mean success.


def test_parallel_credentials_and_framework_home_are_invocation_scoped(
    cli, tmp_path, monkeypatch
):
    monkeypatch.setenv("A2APP_TOKEN", "ambient-token")
    monkeypatch.setenv("A2APP_HOME", "ambient-home")

    async def run():
        return await asyncio.gather(
            cli.run(
                "a2app",
                ["echo"],
                cwd=tmp_path,
                env_extra={"A2APP_TOKEN": "first-token", "A2APP_HOME": "wrong-home"},
            ),
            cli.run(
                "a2app",
                ["echo"],
                cwd=tmp_path,
                env_extra={"A2APP_TOKEN": "second-token"},
            ),
            cli.run("a2app", ["echo"], cwd=tmp_path),
        )

    results = asyncio.run(run())
    assert [result.json()["token"] for result in results] == [
        "first-token",
        "second-token",
        None,
    ]
    assert all(Path(result.json()["home"]) == cli.home for result in results)
    assert os.environ["A2APP_TOKEN"] == "ambient-token"
    assert os.environ["A2APP_HOME"] == "ambient-home"


def test_streams_ndjson_before_exit_and_flushes_partial_final_line(cli, tmp_path):
    async def run():
        first_line = asyncio.Event()
        lines = []

        def collect(line):
            lines.append(line)
            first_line.set()

        release = tmp_path / "release"
        task = asyncio.create_task(
            cli.run(
                "agent-app",
                ["stream", str(release)],
                cwd=tmp_path,
                on_stdout_line=collect,
            )
        )
        try:
            await asyncio.wait_for(first_line.wait(), 5)
            assert not task.done(), "events must arrive while the CLI is still running"
            assert json.loads(lines[0])["step"] == "café"
            release.write_text("release")
            result = await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert result.ok
        assert [json.loads(line)["event"] for line in lines] == ["step", "result"]
        assert result.stdout.endswith('{"event":"result","ok":true}')
        assert result.json() is None  # NDJSON is not a single result document.
        assert result.stderr == "diagnostic\n" * 10000

    asyncio.run(run())


def test_timeout_stops_the_command_tree_and_keeps_partial_output(
    cli, tmp_path, processes
):
    async def run():
        result = await cli.run(
            "agent-app",
            ["tree"],
            cwd=tmp_path,
            timeout=2,
            on_stdout_line=lambda line: remember(line, processes),
        )
        assert len(processes) == 2
        assert result.timed_out and result.code == 124 and not result.ok
        assert result.json()["childPid"] == processes[1].pid
        await assert_stopped(processes)

    asyncio.run(run())


def test_cancellation_stops_the_command_tree(cli, tmp_path, processes):
    async def run():
        started = asyncio.Event()

        def collect(line):
            remember(line, processes)
            started.set()

        task = asyncio.create_task(
            cli.run("agent-app", ["tree"], cwd=tmp_path, on_stdout_line=collect)
        )
        try:
            await asyncio.wait_for(started.wait(), 5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(processes) == 2
        await assert_stopped(processes)

    asyncio.run(run())


def test_callback_failure_stops_the_command_tree(cli, tmp_path, processes):
    def broken_callback(line):
        remember(line, processes)
        raise ValueError("UI subscriber failed")

    async def run():
        with pytest.raises(ValueError, match="UI subscriber failed"):
            await cli.run(
                "agent-app", ["tree"], cwd=tmp_path, on_stdout_line=broken_callback
            )
        await assert_stopped(processes)

    asyncio.run(run())


def test_cancellation_during_spawn_retains_the_process_handle(
    cli, tmp_path, processes, monkeypatch
):
    async def run():
        original = asyncio.create_subprocess_exec
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed_spawn(*args, **kwargs):
            proc = await original(*args, **kwargs)
            line = await asyncio.wait_for(proc.stdout.readline(), 5)
            remember(line, processes)
            started.set()
            await release.wait()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
        task = asyncio.create_task(cli.run("agent-app", ["tree"], cwd=tmp_path))
        try:
            await asyncio.wait_for(started.wait(), 5)
        finally:
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(processes) == 2
        await assert_stopped(processes)

    asyncio.run(run())


def test_excessive_output_fails_and_stops_the_command(
    cli, tmp_path, processes, monkeypatch
):
    monkeypatch.setattr(framework_cli, "MAX_OUTPUT_BYTES", 1024)

    async def run():
        with pytest.raises(RuntimeError, match="output exceeded"):
            await cli.run(
                "agent-app",
                ["flood"],
                cwd=tmp_path,
                on_stdout_line=lambda line: remember(line, processes),
            )
        assert len(processes) == 1
        await assert_stopped(processes)

    asyncio.run(run())


def test_missing_package_reports_the_entrypoint(tmp_path):
    cli = AgentAppCLI(tmp_path / "missing", home=tmp_path / "home")
    with pytest.raises(FrameworkCLIUnavailable, match="entry point is missing"):
        asyncio.run(cli.run("agent-app", ["help"], cwd=tmp_path))


@pytest.mark.parametrize(
    "surface,args,timeout,error",
    [
        ("promote", ["help"], 1, ValueError),
        ("agent-app", "help --json", 1, TypeError),
        ("agent-app", ["help"], 0, ValueError),
        ("agent-app", ["help"], float("inf"), ValueError),
    ],
)
def test_invalid_invocation_is_rejected_before_resolution(
    tmp_path, surface, args, timeout, error
):
    cli = AgentAppCLI(tmp_path / "missing", home=tmp_path / "home")
    with pytest.raises(error):
        asyncio.run(cli.run(surface, args, cwd=tmp_path, timeout=timeout))


def test_missing_node_reports_configuration_hint(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(node_runtime, "resolve", lambda: None)
    with pytest.raises(FrameworkCLIUnavailable, match="CRAFTBOT_NODE"):
        asyncio.run(cli.run("agent-app", ["help"], cwd=tmp_path))


def test_resolution_does_not_block_the_event_loop(cli, tmp_path, monkeypatch):
    import threading

    original = node_runtime.resolve
    loop_thread = threading.get_ident()

    def resolve():
        assert threading.get_ident() != loop_thread
        return original()

    monkeypatch.setattr(node_runtime, "resolve", resolve)
    assert asyncio.run(cli.run("agent-app", ["help"], cwd=tmp_path)).ok


@pytest.mark.skipif(
    not os.environ.get("CRAFTBOT_TEST_AGENT_APP_PACKAGE"),
    reason="set the unchanged built CLI package path to run this smoke test",
)
def test_unchanged_framework_entrypoints_and_empty_registry(tmp_path):
    package = Path(os.environ["CRAFTBOT_TEST_AGENT_APP_PACKAGE"])
    cli = AgentAppCLI(package, home=tmp_path / "isolated framework home")
    version = json.loads((package / "package.json").read_text(encoding="utf-8"))[
        "version"
    ]

    async def run():
        for surface in ("agent-app", "a2app"):
            result = await cli.run(surface, ["--version"], cwd=tmp_path)
            assert result.ok, result.stderr
            assert result.json()[surface] == version
        listing = await cli.run("agent-app", ["list", "--json"], cwd=tmp_path)
        assert listing.ok, listing.stderr
        assert listing.json()["apps"] == []

    asyncio.run(run())
