"""Messages-compatible facade over Claude Code's documented print mode.

CraftBot owns the agent loop. The CLI supplies inference only, with its
tools, MCP servers, hooks and session persistence disabled. Each call sends
the complete conversation as a labelled transcript in one user message;
image blocks remain native image input. Claude Code owns authentication.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent_core.core.models.reasoning import reasoning_options
from craftos_integrations.llm_oauth import claude_code


def _content(messages: list[dict]) -> list[dict]:
    # A single message renders in the same labelled shape as a longer
    # conversation, so each call's blocks are a prefix of the next call's
    # and the CLI's prompt cache carries over from turn 1 to turn 2.
    blocks = [
        {
            "type": "text",
            "text": "Continue this conversation by replying to its final user message.",
        }
    ]
    for message in messages:
        blocks.append({"type": "text", "text": f"\n[{message['role']}]\n"})
        content = message.get("content", "")
        if isinstance(content, str):
            blocks.append({"type": "text", "text": content})
            continue
        for block in content:
            if block.get("type") in ("thinking", "redacted_thinking"):
                continue
            if block.get("type") not in ("text", "image"):
                raise ValueError(
                    "Claude Code inference supports text and image messages only."
                )
            blocks.append({k: v for k, v in block.items() if k != "cache_control"})
    return blocks


def _event(line: str):
    """One stream-json output line as a dict, or None."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _text_delta(event: dict) -> str:
    """The reply text a partial-message line carries ("" for any other)."""
    if event.get("type") != "stream_event":
        return ""
    inner = event.get("event") or {}
    if inner.get("type") != "content_block_delta":
        return ""
    delta = inner.get("delta") or {}
    if delta.get("type") != "text_delta":
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


class ClaudeCodeClient:
    def __init__(self, *, timeout: float = 600):
        self.timeout = timeout
        self.messages = self

    def _run_streamed(self, args, stdin_text, directory, env, sink):
        """Run the CLI, handing the reply's text to ``sink`` line by line.

        Returns (returncode, result line). A watcher ends the process when
        the caller stops the reply (LLMStreamAborted) or the timeout passes.
        """
        import threading
        import time

        from agent_core.core.impl.llm.streaming import LLMStreamAborted, begin, emit

        begin(sink)
        proc = claude_code.open_cli(args, cwd=directory, env_overrides=env)
        stderr_lines: list[str] = []
        timed_out = threading.Event()

        def drain_stderr():
            for line in iter(proc.stderr.readline, ""):
                stderr_lines.append(line)

        def watch():
            deadline = time.monotonic() + self.timeout
            while proc.poll() is None:
                if sink.cancelled or time.monotonic() > deadline:
                    if not sink.cancelled:
                        timed_out.set()
                    proc.kill()
                    return
                time.sleep(0.1)

        reader = threading.Thread(target=drain_stderr, daemon=True)
        watcher = threading.Thread(target=watch, daemon=True)
        reader.start()
        watcher.start()
        final = None
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
            for line in iter(proc.stdout.readline, ""):
                event = _event(line)
                if event is None:
                    continue
                if event.get("type") == "result":
                    final = event
                    continue
                text = _text_delta(event)
                if text:
                    emit(sink, text)
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            watcher.join(timeout=1)
            reader.join(timeout=1)
        if sink.cancelled:
            raise LLMStreamAborted()
        if timed_out.is_set():
            raise RuntimeError("Claude Code inference timed out.")
        return proc.returncode, final

    def create(
        self,
        *,
        model: str,
        messages: list[dict],
        system=None,
        max_tokens: int = 16384,
        thinking=None,
        output_config=None,
        extra_body=None,
    ):
        if not claude_code.has_credential():
            raise RuntimeError(
                "Claude subscription disconnected. Reconnect in Settings or save an API key."
            )
        if isinstance(system, list):
            system = "\n\n".join(block.get("text", "") for block in system)
        payload = {
            "type": "user",
            "message": {"role": "user", "content": _content(messages)},
        }
        env = {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_tokens)}
        # The Messages API omits thinking for Off on Claude 4.x; the CLI
        # enables it by default. Use the same model rules as the transport
        # so models whose provider default includes thinking keep it.
        options = reasoning_options("anthropic", model, "subscription")
        omitted_means_off = (
            thinking is None
            and options is not None
            and options.provider_default == "off"
        )
        if omitted_means_off or (thinking and thinking.get("type") == "disabled"):
            env["MAX_THINKING_TOKENS"] = "0"
        elif thinking and thinking.get("budget_tokens") is not None:
            env["MAX_THINKING_TOKENS"] = str(thinking["budget_tokens"])

        # File + stdin inputs avoid OS command-line limits and shell escaping,
        # even with large system prompts or base64 screenshots on Windows.
        with tempfile.TemporaryDirectory(prefix="craftbot-claude-") as directory:
            root = Path(directory)
            prompt = root / "system.txt"
            prompt.write_text(
                system or "You are a helpful assistant.", encoding="utf-8"
            )
            settings = root / "settings.json"
            settings.write_text('{"disableAllHooks":true}', encoding="utf-8")
            mcp = root / "mcp.json"
            mcp.write_text('{"mcpServers":{}}', encoding="utf-8")
            args = [
                "--print",
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",
                "--model",
                model,
                "--max-turns",
                "1",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                str(mcp),
                "--setting-sources",
                "",
                "--settings",
                str(settings),
                "--no-session-persistence",
                "--disable-slash-commands",
                "--system-prompt-file",
                str(prompt),
            ]
            effort = (output_config or {}).get("effort")
            if effort:
                args.extend(["--effort", effort])
            from agent_core.core.impl.llm.streaming import current_sink

            sink = current_sink()
            if sink is not None:
                # Partial messages only add output lines (the reply's text
                # as it is written); the request the CLI sends is the same.
                args.append("--include-partial-messages")
                returncode, final = self._run_streamed(
                    args, json.dumps(payload) + "\n", directory, env, sink
                )
            else:
                try:
                    result = claude_code.run_cli(
                        args,
                        input=json.dumps(payload) + "\n",
                        cwd=directory,
                        env_overrides=env,
                        timeout=self.timeout,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("Claude Code inference timed out.") from exc
                returncode = result.returncode
                final = None
                for line in result.stdout.splitlines():
                    event = _event(line)
                    if event is not None and event.get("type") == "result":
                        final = event

        if final is None:
            raise RuntimeError(
                "Claude Code did not return a result. Update the CLI and reconnect "
                "in Settings using CraftBot's separate Claude profile."
            )
        if returncode or final.get("is_error"):
            detail = final.get("result") or "; ".join(final.get("errors") or [])
            raise RuntimeError(
                f"Claude Code inference failed: {detail or final.get('subtype', 'unknown error')}"
            )
        usage = final.get("usage") or {}
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=final.get("result") or "")],
            usage=SimpleNamespace(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
            ),
        )
