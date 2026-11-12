"""CraftBot transport for an unchanged, built Agent-App CLI package.

The caller supplies the package directory, framework home and working directory.
No global CLI installation, app registry or lifecycle policy lives here.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import math
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

from app import node_runtime
from app.process_ledger import kill_tree

Surface = Literal["agent-app", "a2app"]
MAX_OUTPUT_BYTES = 8 * 1024 * 1024  # Per stream; excessive output fails explicitly.


class FrameworkCLIUnavailable(RuntimeError):
    """The selected package or CraftBot's Node runtime is unavailable."""


def _import_default_ref(source: str) -> str:
    """Resolve bare GitHub URLs without changing explicit refs or other sources."""
    parsed = urlsplit(source)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() not in {"github.com", "www.github.com"}
        or len(parts) != 2
        or not all(parts)
    ):
        return ""
    owner, repo = (unquote(part) for part in parts)
    repo = repo.removesuffix(".git")
    request = Request(
        f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "CraftBot"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            metadata = json.loads(response.read(1024 * 1024))
        branch = metadata.get("default_branch") if isinstance(metadata, dict) else None
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("GitHub did not return a default branch")
        return branch
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"Could not read the default branch for {owner}/{repo}: {exc}. "
            "Retry, or paste a GitHub URL containing /tree/<branch>."
        ) from exc


@dataclass(frozen=True)
class CLIResult:
    code: int
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    def json(self):
        """Decode a complete JSON document; text and NDJSON remain raw output."""
        try:
            return json.loads(self.stdout)
        except json.JSONDecodeError:
            return None


class AgentAppCLI:
    def __init__(self, package_dir: Path, *, home: Path):
        self.package_dir = Path(package_dir).resolve()
        self.home = Path(home).resolve()

    def _prepare(self, surface: Surface, env_extra: Mapping[str, str]):
        entry = self.package_dir / "bin" / f"{surface}.js"
        if not entry.is_file():
            raise FrameworkCLIUnavailable(
                f"Agent-App entry point is missing: {entry}. "
                "Select the built agent-app-framework package directory."
            )
        runtime = node_runtime.resolve()
        if runtime is None:
            raise FrameworkCLIUnavailable(
                "No CraftBot Node runtime found. Configure CRAFTBOT_NODE or run the CraftBot installer."
            )
        major = node_runtime.major_of(runtime.version)
        if major is not None and major < 20:
            raise FrameworkCLIUnavailable("The Agent-App CLI requires Node.js >= 20.")
        executable = Path(runtime.node).resolve()
        if not executable.is_file():
            raise FrameworkCLIUnavailable(
                "The selected CraftBot Node executable is missing."
            )
        env = node_runtime.child_env()
        # Match the branch used by CraftBot's marketplace cards. The upstream
        # CLI still owns repository fallback and explicit --source handling.
        from app.agent_app.marketplace_source import ref
        from app.config import get_framework_toolkits_dir

        env["A2APP_MARKETPLACE_REF"] = ref()
        toolkits = get_framework_toolkits_dir()
        if not (
            env_extra.get("A2APP_TOOLKITS_DIR") or env.get("A2APP_TOOLKITS_DIR", "")
        ).strip():
            if not toolkits:
                from app import paths
                from app.provision.default_agent_app import bundled_toolkits

                toolkits = str(bundled_toolkits(paths.CODE_ROOT, paths.STATE_ROOT))
            env["A2APP_TOOLKITS_DIR"] = toolkits
        # A delegated run must not inherit another run's ambient credential.
        env.pop("A2APP_TOKEN", None)
        env.update(env_extra)
        env["A2APP_HOME"] = str(self.home)
        return [str(executable), str(entry)], env

    async def run(
        self,
        surface: Surface,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 600,
        env_extra: Mapping[str, str] | None = None,
        on_stdout_line: Callable[[str], None] | None = None,
    ) -> CLIResult:
        """Run literal argv and preserve the CLI exit code and separate streams.

        The synchronous line callback receives stdout as it arrives, including
        install --events NDJSON. It must return quickly; callback failures abort
        the invocation. Timeouts return code 124; caller cancellation propagates
        after command-process cleanup. Detached apps remain framework-managed.
        """
        if surface not in ("agent-app", "a2app"):
            raise ValueError("surface must be 'agent-app' or 'a2app'")
        if isinstance(args, (str, bytes)):
            raise TypeError("args must be a sequence of strings, not a shell command")
        argv = list(args)
        if any(not isinstance(arg, str) for arg in argv):
            raise TypeError("args must contain only strings")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and greater than zero")
        extra = dict(env_extra or {})
        if (
            surface == "agent-app"
            and argv
            and argv[0] in {"inspect", "install"}
            and "--from" in argv
        ):
            # Upstream uses this per-command default for bare GitHub URLs too.
            # Keep the URL intact and isolate imports from the catalogue branch.
            extra["A2APP_MARKETPLACE_REF"] = ""
            source_index = argv.index("--from") + 1
            if source_index < len(argv):
                extra["A2APP_MARKETPLACE_REF"] = await asyncio.to_thread(
                    _import_default_ref, argv[source_index]
                )
        # Resolution can probe Node synchronously; keep it off the UI event loop.
        command, env = await asyncio.to_thread(self._prepare, surface, extra)
        flags = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if sys.platform == "win32"
            else {"start_new_session": True}
        )
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *command,
                *argv,
                cwd=str(Path(cwd).resolve()),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **flags,
            )
        )
        try:
            proc = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            # Cancellation during spawn must not lose the process handle.
            proc = await spawning
            await _terminate(proc)
            raise
        stdout: list[bytes] = []
        stderr: list[bytes] = []
        readers = [
            asyncio.create_task(_read(proc.stdout, stdout, on_stdout_line)),
            asyncio.create_task(_read(proc.stderr, stderr, None)),
        ]
        completion = asyncio.gather(*readers, proc.wait())
        timed_out = False
        try:
            done, _ = await asyncio.wait([completion], timeout=timeout)
            if not done:
                timed_out = True
                await _terminate(proc)
                # A detached descendant may still hold an inherited pipe open.
                await asyncio.wait_for(asyncio.shield(completion), timeout=5)
            else:
                await completion
        except BaseException:
            await _terminate(proc)
            raise
        finally:
            for reader in readers:
                reader.cancel()
            completion.cancel()
            await asyncio.gather(*readers, completion, return_exceptions=True)
        return CLIResult(
            code=124 if timed_out else proc.returncode,
            stdout=b"".join(stdout).decode("utf-8", errors="replace"),
            stderr=b"".join(stderr).decode("utf-8", errors="replace"),
            timed_out=timed_out,
        )


async def _read(stream, chunks: list[bytes], on_line: Callable[[str], None] | None):
    size = 0
    pending = ""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while chunk := await stream.read(64 * 1024):
        size += len(chunk)
        if size > MAX_OUTPUT_BYTES:
            raise RuntimeError("Agent-App CLI output exceeded the per-stream limit.")
        chunks.append(chunk)
        if on_line is not None:
            pending += decoder.decode(chunk)
            lines = pending.split("\n")
            pending = lines.pop()
            for line in lines:
                on_line(line.removesuffix("\r"))
    if on_line is not None:
        pending += decoder.decode(b"", final=True)
        if pending:
            on_line(pending.removesuffix("\r"))


async def _terminate(proc):
    """Stop only this invocation's command tree; never discover apps by port."""
    try:
        if sys.platform == "win32":
            if proc.returncode is None:
                await asyncio.to_thread(kill_tree, proc.pid, grace=0)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await asyncio.wait_for(proc.wait(), timeout=5)
