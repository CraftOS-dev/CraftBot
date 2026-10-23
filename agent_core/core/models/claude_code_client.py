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
    blocks = []
    if len(messages) > 1:
        blocks.append(
            {
                "type": "text",
                "text": "Continue this conversation by replying to its final user message.",
            }
        )
    for message in messages:
        if len(messages) > 1:
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


class ClaudeCodeClient:
    def __init__(self, *, timeout: float = 600):
        self.timeout = timeout
        self.messages = self

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

        final = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                final = event
        if final is None:
            raise RuntimeError(
                "Claude Code did not return a result. Update the CLI and reconnect "
                "in Settings using CraftBot's separate Claude profile."
            )
        if result.returncode or final.get("is_error"):
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
