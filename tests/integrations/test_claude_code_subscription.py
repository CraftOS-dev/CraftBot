"""Claude subscription routing must never export OAuth tokens or bill an API key."""

import asyncio
import json
import queue
import subprocess
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations.llm_oauth import claude_code, tokens
from agent_core.core.models.claude_code_client import ClaudeCodeClient
from agent_core.core.models.factory import ModelFactory
from agent_core.core.models.types import InterfaceType


@pytest.fixture(autouse=True)
def isolated_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    monkeypatch.setattr(claude_code, "_login_process", None)
    monkeypatch.setattr(claude_code, "_login_generation", 0)
    # Never find the real CLI installed on the test machine.
    monkeypatch.setattr(claude_code, "_native_install", lambda: tmp_path / "no-claude")


@pytest.fixture(autouse=True)
def opened(monkeypatch):
    pages = []
    monkeypatch.setattr(webbrowser, "open", pages.append)
    return pages


class FakeLogin:
    """`claude auth login` without a terminal: opens its own browser tab and
    exits once the user approves there, with one code exchange."""

    def __init__(self, args, *, env, outcome="approve", on_success=None, **kwargs):
        self.args, self.env, self.on_success = args, env, on_success
        self.lines = queue.Queue()
        self.received = []
        self.returncode = None
        self.exited = threading.Event()
        self.stdout = SimpleNamespace(readline=self.lines.get)
        self.stdin = SimpleNamespace(write=self.received.append, flush=lambda: None)
        self.lines.put(b"Opening browser to sign in\n")
        if outcome == "approve":
            threading.Timer(0.05, self._approve).start()
        elif outcome == "reject":
            threading.Timer(0.05, self._reject).start()

    def _approve(self):
        if self.on_success:
            self.on_success()
        self._exit(0, "Login successful.")

    def _reject(self):
        self._exit(
            1,
            "Paste code here if prompted > Login failed: "
            "Request failed with status code 400",
        )

    def _exit(self, code, line):
        if self.returncode is not None:
            return
        self.lines.put(line.encode() + b"\n")
        self.lines.put(b"")
        self.returncode = code
        self.exited.set()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self.exited.wait(timeout):
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.returncode

    def kill(self):
        self._exit(1, "")


def fake_cli(monkeypatch, **behaviour):
    launched = []

    def popen(args, **kwargs):
        launched.append(FakeLogin(args, **kwargs, **behaviour))
        return launched[-1]

    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])
    monkeypatch.setattr(claude_code.subprocess, "Popen", popen)
    return launched


def claude_account(monkeypatch):
    """A private profile that is signed out until the CLI's tab is approved.
    Returns the hook that signs it in."""
    state = {"signed_in": False}
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda: (
            {"connected": True, "email": "user@example.com", "plan": "max"}
            if state["signed_in"]
            else {"connected": False, "error": "Use Connect"}
        ),
    )
    return lambda: state.update(signed_in=True)


def connected(monkeypatch):
    def signed_out_cli(args, **kwargs):
        assert args in (["auth", "logout"], ["auth", "status"])
        return SimpleNamespace(returncode=0, stdout='{"loggedIn": false}')

    monkeypatch.setattr(claude_code, "run_cli", signed_out_cli)
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda: {
            "connected": True,
            "email": "user@example.com",
            "plan": "max",
        },
    )
    assert asyncio.run(tokens.connect("anthropic"))[0]


def test_connection_is_explicit_and_does_not_store_cli_credentials(
    monkeypatch, tmp_path
):
    assert not tokens.has_credential("anthropic")
    assert tokens.status("anthropic") == {"supported": True, "connected": False}
    connected(monkeypatch)
    assert tokens.has_credential("anthropic")
    assert tokens.status("anthropic")["email"] == "user@example.com"
    assert tokens.get_bearer("anthropic") is None
    assert json.loads(
        (tmp_path / ".credentials" / claude_code.CRED_FILE).read_text()
    ) == {
        "enabled": True,
        "profile_version": claude_code.PROFILE_VERSION,
    }


def test_disconnect_logs_out_then_verifies_before_clearing_marker(monkeypatch):
    connected(monkeypatch)
    calls = []

    def logout(args, **kwargs):
        assert tokens.has_credential("anthropic")
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='{"loggedIn": false}')

    monkeypatch.setattr(claude_code, "run_cli", logout)
    assert tokens.disconnect("anthropic")[0]
    assert calls == [["auth", "logout"], ["auth", "status"]]
    assert not tokens.has_credential("anthropic")


@pytest.mark.parametrize(
    "method", ["api_key", "api_key_helper", "third_party", "oauth_token"]
)
def test_auth_status_rejects_non_subscription_auth(monkeypatch, method):
    monkeypatch.setattr(
        claude_code,
        "run_cli",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"loggedIn": True, "authMethod": method}),
        ),
    )
    assert not claude_code.auth_status()["connected"]


def test_connect_adopts_an_existing_private_sign_in_without_a_browser(monkeypatch):
    monkeypatch.setattr(
        claude_code, "auth_status", lambda: {"connected": True, "email": "a@b.c"}
    )
    monkeypatch.setattr(
        claude_code.subprocess, "Popen", lambda *a, **k: pytest.fail("No login")
    )
    assert asyncio.run(tokens.connect("anthropic"))[0]
    assert tokens.has_credential("anthropic")


def test_connect_waits_for_approval_in_the_cli_tab(monkeypatch, opened):
    launched = fake_cli(monkeypatch, on_success=claude_account(monkeypatch))
    ok, message = asyncio.run(tokens.connect("anthropic"))
    assert ok and "user@example.com" in message
    login = launched[0]
    assert login.args == ["claude", "auth", "login"]
    assert login.env["CLAUDE_CONFIG_DIR"] == str(claude_code.profile_directory())
    # The CLI opens the only tab, and no code passes through CraftBot.
    assert opened == [] and login.received == []
    assert tokens.has_credential("anthropic")


def test_failed_approval_is_reported_and_does_not_connect(monkeypatch):
    claude_account(monkeypatch)
    fake_cli(monkeypatch, outcome="reject")
    ok, message = asyncio.run(tokens.connect("anthropic"))
    assert not ok and "Login failed: Request failed" in message
    assert "Paste code here" not in message
    assert not tokens.has_credential("anthropic")


def test_abandoned_sign_in_times_out(monkeypatch):
    claude_account(monkeypatch)
    launched = fake_cli(monkeypatch, outcome="abandon")
    monkeypatch.setattr(claude_code, "LOGIN_TIMEOUT_SECONDS", 0.2)
    ok, message = asyncio.run(tokens.connect("anthropic"))
    assert not ok and "timed out" in message
    assert launched[0].returncode is not None
    assert not tokens.has_credential("anthropic")


def test_new_connect_replaces_an_abandoned_sign_in(monkeypatch):
    signed_in = claude_account(monkeypatch)
    outcomes = iter(["abandon", "approve"])
    launched = []

    def popen(args, **kwargs):
        launched.append(
            FakeLogin(args, **kwargs, outcome=next(outcomes), on_success=signed_in)
        )
        return launched[-1]

    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])
    monkeypatch.setattr(claude_code.subprocess, "Popen", popen)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(asyncio.run, tokens.connect("anthropic"))
        while claude_code._login_process is None:
            threading.Event().wait(0.01)
        ok, _ = asyncio.run(tokens.connect("anthropic"))
        assert ok
        ok, message = first.result(timeout=5)
    assert not ok and "replaced" in message
    assert tokens.has_credential("anthropic")


def test_cli_that_cannot_start_says_why(monkeypatch):
    claude_account(monkeypatch)
    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])

    def blocked(*args, **kwargs):
        raise OSError("blocked by policy")

    monkeypatch.setattr(claude_code.subprocess, "Popen", blocked)
    ok, message = asyncio.run(tokens.connect("anthropic"))
    assert not ok and "blocked by policy" in message


def test_settings_connect_button_flips_to_connected(monkeypatch):
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter
    from app.ui_layer.settings import provider_settings

    fake_cli(monkeypatch, on_success=claude_account(monkeypatch))
    modes = []
    monkeypatch.setattr(
        provider_settings, "_persist_auth_mode", lambda *args: modes.append(args)
    )
    adapter = object.__new__(BrowserAdapter)
    sent = []

    async def broadcast(message):
        sent.append(message)

    adapter._broadcast = broadcast

    async def activate(ok, provider, **kwargs):
        return provider if ok else None

    adapter._activate_provider_via_settings = activate
    asyncio.run(adapter._handle_model_subscription_connect("anthropic"))
    assert [m["type"] for m in sent] == ["model_subscription_connect"]
    result = sent[0]["data"]
    assert result["success"] and result["active_provider"] == "anthropic"
    assert result["status"]["connected"]
    assert modes == [("anthropic", "subscription")]


def test_inherited_api_auth_and_nested_session_do_not_override_subscription(
    monkeypatch,
):
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDECODE",
        "MAX_THINKING_TOKENS",
        "CLAUDE_CODE_EFFORT_LEVEL",
        "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
    ):
        monkeypatch.setenv(name, "must-not-reach-cli")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/my/claude/config")
    env = claude_code.cli_environment()
    assert "must-not-reach-cli" not in env.values()
    assert env["CLAUDE_CONFIG_DIR"] == str(claude_code.profile_directory())
    assert env["CLAUDE_CONFIG_DIR"] != "/my/claude/config"
    assert claude_code.os.environ["CLAUDE_CONFIG_DIR"] == "/my/claude/config"


def test_factory_uses_cli_before_api_key_and_reverts_after_disconnect(monkeypatch):
    connected(monkeypatch)
    ctx = ModelFactory.create(
        provider="anthropic", interface=InterfaceType.LLM, api_key="paid-key"
    )
    assert isinstance(ctx["anthropic_client"], ClaudeCodeClient)
    assert ctx["auth_mode"] == "subscription"
    tokens.disconnect("anthropic")
    client = object()
    monkeypatch.setattr(
        "agent_core.core.models.factory._create_anthropic_client", lambda **k: client
    )
    ctx = ModelFactory.create(
        provider="anthropic", interface=InterfaceType.LLM, api_key="paid-key"
    )
    assert ctx["anthropic_client"] is client
    assert "auth_mode" not in ctx


def test_request_preserves_text_images_and_usage_without_running_tools(monkeypatch):
    connected(monkeypatch)
    prompt = "system instructions " * 10000
    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "abc"},
    }
    temporary_paths = []

    def run(args, **kwargs):
        assert "--tools" in args and args[args.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in args
        assert "--no-session-persistence" in args
        assert Path(args[args.index("--system-prompt-file") + 1]).read_text() == prompt
        settings = Path(args[args.index("--settings") + 1])
        assert json.loads(settings.read_text())["disableAllHooks"]
        assert json.loads(Path(args[args.index("--mcp-config") + 1]).read_text()) == {
            "mcpServers": {}
        }
        temporary_paths.append(settings.parent)
        blocks = json.loads(kwargs["input"])["message"]["content"]
        assert image in blocks
        texts = " ".join(b.get("text", "") for b in blocks)
        assert (
            "earlier question" in texts
            and "earlier answer" in texts
            and "latest question" in texts
        )
        assert "[assistant]" in texts
        assert kwargs["env_overrides"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "123"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "result": "answer",
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 10,
                    },
                }
            ),
        )

    monkeypatch.setattr(claude_code, "run_cli", run)
    result = ClaudeCodeClient().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=123,
        system=[
            {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
            {
                "role": "user",
                "content": [image, {"type": "text", "text": "latest question"}],
            },
        ],
    )
    assert result.content[0].text == "answer"
    assert result.usage.input_tokens == 20
    assert result.usage.cache_read_input_tokens == 10
    assert all(not path.exists() for path in temporary_paths)


@pytest.mark.parametrize(
    "stdout,code",
    [
        ("not json", 1),
        (json.dumps({"type": "result", "is_error": True, "result": "rate limited"}), 0),
    ],
)
def test_cli_failure_is_not_silently_billed_to_api_key(monkeypatch, stdout, code):
    connected(monkeypatch)
    monkeypatch.setattr(
        claude_code,
        "run_cli",
        lambda *a, **k: SimpleNamespace(returncode=code, stdout=stdout),
    )
    with pytest.raises(RuntimeError, match="Claude Code"):
        ClaudeCodeClient().create(
            model="sonnet", messages=[{"role": "user", "content": "hi"}]
        )


def test_existing_client_stops_after_disconnect(monkeypatch):
    connected(monkeypatch)
    client = ClaudeCodeClient()
    tokens.disconnect("anthropic")
    monkeypatch.setattr(
        claude_code, "run_cli", lambda *a, **k: pytest.fail("Disconnected")
    )
    with pytest.raises(RuntimeError, match="disconnected"):
        client.create(model="sonnet", messages=[{"role": "user", "content": "hi"}])


def test_settings_allow_connected_claude_without_api_key(monkeypatch):
    from app.ui_layer.settings import model_settings

    monkeypatch.setattr(model_settings, "_load_settings", lambda: {})
    assert not model_settings.validate_can_save("anthropic")["success"]
    connected(monkeypatch)
    assert model_settings.validate_can_save("anthropic")["success"]
    info = next(
        p
        for p in model_settings.get_available_providers()["providers"]
        if p["id"] == "anthropic"
    )
    assert info["supports_subscription_oauth"]
    assert info["subscription_label"] == "Sign in with Claude"
    from app.onboarding.interfaces.steps import ApiKeyStep

    assert ApiKeyStep("anthropic").subscription_label() == "Sign in with Claude"


def test_connection_test_uses_selected_cli_model(monkeypatch):
    from agent_core.core.models.connection_tester import test_provider_connection

    connected(monkeypatch)
    calls = []
    monkeypatch.setattr(
        ClaudeCodeClient, "create", lambda self, **kwargs: calls.append(kwargs)
    )
    result = test_provider_connection(
        "anthropic", api_key="unused-paid-key", model="claude-sonnet-4-6"
    )
    assert result["success"]
    assert calls[0]["model"] == "claude-sonnet-4-6"


def test_windows_npm_cli_bypasses_shell(monkeypatch, tmp_path):
    shim = tmp_path / "claude.cmd"
    entry = tmp_path / "node_modules/@anthropic-ai/claude-code/cli.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("// official CLI entrypoint")
    monkeypatch.setattr(
        claude_code.shutil,
        "which",
        lambda name: str(shim) if name == "claude" else "node.exe",
    )
    assert claude_code.cli_command() == ["node.exe", str(entry)]


def test_missing_cli_has_install_instructions(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    success, message = asyncio.run(tokens.connect("anthropic"))
    assert not success and "Install" in message


def test_native_install_is_used_when_app_path_is_stale(monkeypatch, tmp_path):
    native = tmp_path / "claude.exe"
    native.write_text("")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    monkeypatch.setattr(claude_code, "_native_install", lambda: native)
    assert claude_code.cli_command() == [str(native)]


def test_status_detects_cli_logout_without_exporting_tokens(monkeypatch):
    connected(monkeypatch)
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda: {"connected": False, "error": "Sign in again"},
    )
    assert not tokens.status("anthropic")["connected"]
    assert tokens.status("anthropic")["configured"]
    assert tokens.get_bearer("anthropic") is None


def test_invalid_login_can_disconnect_before_switching_to_an_api_key(monkeypatch):
    from app.ui_layer.settings import provider_settings
    from agent_core.core.models import connection_tester

    connected(monkeypatch)
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda: {"connected": False, "error": "Sign in again"},
    )
    monkeypatch.setattr(provider_settings, "_persist_auth_mode", lambda *args: None)
    assert tokens.status("anthropic") == {
        "supported": True,
        "configured": True,
        "connected": False,
        "error": "Sign in again",
    }
    # A failed login never silently selects the paid API key.
    context = ModelFactory.create(
        provider="anthropic", interface=InterfaceType.LLM, api_key="paid-key"
    )
    assert isinstance(context["anthropic_client"], ClaudeCodeClient)
    # Disconnect still verifies the already-logged-out CLI before clearing opt-in.
    assert provider_settings.disconnect_subscription("anthropic")[0]
    assert tokens.status("anthropic") == {"supported": True, "connected": False}
    api_client = object()
    monkeypatch.setattr(
        "agent_core.core.models.factory._create_anthropic_client",
        lambda **kwargs: api_client,
    )
    context = ModelFactory.create(
        provider="anthropic", interface=InterfaceType.LLM, api_key="paid-key"
    )
    assert context["anthropic_client"] is api_client
    tested = []
    monkeypatch.setattr(
        connection_tester,
        "_test_anthropic",
        lambda key, *args: tested.append(key) or {"success": True},
    )
    assert connection_tester.test_provider_connection("anthropic", api_key="paid-key")[
        "success"
    ]
    assert tested == ["paid-key"]


def test_failed_logout_verification_keeps_disconnect_available(monkeypatch):
    read_status = claude_code.auth_status
    connected(monkeypatch)
    monkeypatch.setattr(claude_code, "auth_status", read_status)
    monkeypatch.setattr(
        claude_code,
        "run_cli",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="invalid status"),
    )
    assert not tokens.disconnect("anthropic")[0]
    status = tokens.status("anthropic")
    assert not status["connected"]
    assert status["configured"] and status["error"]
    # A subsequent successful retry clears both routing and recovery state.
    monkeypatch.setattr(
        claude_code,
        "run_cli",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout='{"loggedIn": false}'
        ),
    )
    assert tokens.disconnect("anthropic")[0]
    assert tokens.status("anthropic") == {"supported": True, "connected": False}


def test_old_shared_login_marker_requires_new_profile_sign_in(tmp_path):
    from craftos_integrations.credentials_store import save_credential

    save_credential(claude_code.CRED_FILE, claude_code.ClaudeCodeConnection())
    assert not tokens.has_credential("anthropic")
    assert tokens.status("anthropic") == {"supported": True, "connected": False}
    assert not (tmp_path / ".credentials" / "claude_code").exists()


def test_all_cli_commands_force_same_private_profile(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/standalone/profile")
    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])
    invocations = []

    def subprocess_run(args, **kwargs):
        invocations.append((args, kwargs["env"]["CLAUDE_CONFIG_DIR"]))
        return SimpleNamespace(returncode=0, stdout='{"loggedIn": false}')

    monkeypatch.setattr(claude_code.subprocess, "run", subprocess_run)
    for args in (
        ["auth", "login"],
        ["auth", "status"],
        ["auth", "logout"],
        ["--print"],
    ):
        claude_code.run_cli(
            args, timeout=10, env_overrides={"CLAUDE_CONFIG_DIR": "/wrong/profile"}
        )
    assert len(invocations) == 4
    assert {path for _, path in invocations} == {str(claude_code.profile_directory())}
    assert claude_code.os.environ["CLAUDE_CONFIG_DIR"] == "/standalone/profile"


def test_profiles_are_scoped_to_craftbot_installation(monkeypatch, tmp_path):
    first = claude_code.profile_directory()
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path / "another-installation")
    assert claude_code.profile_directory() != first


@pytest.mark.parametrize(
    "failure", ["exit", "timeout", "still_logged_in", "invalid_status"]
)
def test_failed_logout_keeps_connection_and_auth_mode(monkeypatch, failure):
    from app.ui_layer.settings import provider_settings

    connected(monkeypatch)
    modes = []
    monkeypatch.setattr(
        provider_settings, "_persist_auth_mode", lambda *args: modes.append(args)
    )

    def fail(args, **kwargs):
        if args == ["auth", "logout"]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired("claude", 30)
            return SimpleNamespace(returncode=1 if failure == "exit" else 0)
        return SimpleNamespace(
            returncode=0,
            stdout='{"loggedIn": true}' if failure == "still_logged_in" else "invalid",
        )

    monkeypatch.setattr(claude_code, "run_cli", fail)
    success, message = provider_settings.disconnect_subscription("anthropic")
    assert not success and message
    assert tokens.has_credential("anthropic")
    assert modes == []


def test_reconnect_after_logout_needs_a_new_sign_in(monkeypatch):
    logged_in = False

    def signed_in():
        nonlocal logged_in
        logged_in = True

    def cli(args, **kwargs):
        nonlocal logged_in
        if args == ["auth", "logout"]:
            logged_in = False
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"loggedIn": logged_in, "authMethod": "claude.ai"}),
        )

    launched = fake_cli(monkeypatch, on_success=signed_in)
    monkeypatch.setattr(claude_code, "run_cli", cli)
    for _ in range(2):
        assert asyncio.run(tokens.connect("anthropic"))[0]
        assert tokens.disconnect("anthropic")[0]
        assert not tokens.has_credential("anthropic")
    assert len(launched) == 2


@pytest.mark.parametrize(
    "model,choice,expected_budget,expected_effort",
    [
        ("claude-sonnet-4-6", "off", "0", None),
        ("claude-sonnet-4-6", "provider_default", "0", None),
        ("claude-sonnet-4-6", "high", None, "high"),
        ("claude-haiku-4-5-20251001", "off", "0", None),
        ("claude-haiku-4-5-20251001", "provider_default", "0", None),
        ("claude-haiku-4-5-20251001", "high", "12288", None),
        ("claude-sonnet-5", "off", "0", None),
        ("claude-sonnet-5", "provider_default", None, None),
        ("claude-sonnet-5-5", "provider_default", None, None),
    ],
)
def test_cli_honors_transport_reasoning_choices(
    monkeypatch, model, choice, expected_budget, expected_effort
):
    from agent_core.core.impl.llm.reasoning_wire import for_anthropic
    from agent_core.core.models.reasoning import ReasoningChoice, resolve_reasoning

    run_cli = claude_code.run_cli
    connected(monkeypatch)
    monkeypatch.setattr(claude_code, "run_cli", run_cli)
    # Standalone CLI preferences must not override this request's choice.
    monkeypatch.setenv("MAX_THINKING_TOKENS", "0")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "low")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING", "1")
    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs["env"]))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"type": "result", "result": "OK"}),
        )

    monkeypatch.setattr(claude_code.subprocess, "run", run)
    applied = for_anthropic(
        resolve_reasoning("anthropic", model, "subscription", ReasoningChoice(choice)),
        16384,
    )
    ClaudeCodeClient().create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=applied.output_cap,
        **applied.fields,
    )
    args, env = calls[0]
    assert env.get("MAX_THINKING_TOKENS") == expected_budget
    assert "CLAUDE_CODE_EFFORT_LEVEL" not in env
    assert "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING" not in env
    effort = args[args.index("--effort") + 1] if "--effort" in args else None
    assert effort == expected_effort


@pytest.mark.parametrize(
    "operation",
    [
        "get",
        "save",
        "image_rollback",
        "video_rollback",
        "connect",
        "complete",
        "ollama",
        "pull",
    ],
)
def test_browser_subscription_checks_run_off_the_event_loop(monkeypatch, operation):
    from app.ui_layer.adapters import browser_adapter
    from app.ui_layer.settings import model_settings
    from app.ui_layer import local_llm_setup

    connected(monkeypatch)
    status_threads = []
    reinit_threads = []
    sent = []

    def status():
        status_threads.append(threading.get_ident())
        return {"connected": True}

    def reinitialize(provider):
        reinit_threads.append(threading.get_ident())
        return True

    async def broadcast(message):
        sent.append(message)

    async def connect(provider):
        return True, "Connected"

    async def pull(*args, **kwargs):
        return {"success": True}

    monkeypatch.setattr(claude_code, "auth_status", status)
    monkeypatch.setattr(model_settings, "_load_settings", lambda: {})
    monkeypatch.setattr(model_settings, "_save_settings", lambda settings: True)
    monkeypatch.setattr("app.config.reload_settings", lambda: None)
    monkeypatch.setattr("app.config.get_image_gen_provider", lambda: "openai")
    monkeypatch.setattr("app.config.get_image_gen_model", lambda: None)
    monkeypatch.setattr("app.config.get_video_gen_provider", lambda: "byteplus")
    monkeypatch.setattr("app.config.get_video_gen_model", lambda: None)
    monkeypatch.setattr(browser_adapter, "connect_subscription_async", connect)
    monkeypatch.setattr(
        browser_adapter, "complete_subscription", lambda *args: (True, "Connected")
    )
    monkeypatch.setattr(
        browser_adapter,
        "get_ollama_models",
        lambda **kwargs: {"success": True, "models": []},
    )
    monkeypatch.setattr(local_llm_setup, "pull_ollama_model", pull)
    adapter = object.__new__(browser_adapter.BrowserAdapter)
    adapter._broadcast = broadcast
    adapter._controller = SimpleNamespace(
        agent=SimpleNamespace(
            reinitialize_llm=reinitialize,
            reinitialize_image_gen=lambda provider: False,
            reinitialize_video_gen=lambda provider: False,
        )
    )

    async def run():
        loop_thread = threading.get_ident()
        if operation == "get":
            await adapter._handle_model_settings_get()
        elif operation == "save":
            await adapter._handle_model_settings_update(
                {"llmModel": "claude-sonnet-4-6"}
            )
        elif operation == "image_rollback":
            await adapter._handle_model_settings_update({"imageGenProvider": "openai"})
        elif operation == "video_rollback":
            await adapter._handle_model_settings_update(
                {"videoGenProvider": "byteplus"}
            )
        elif operation == "connect":
            await adapter._handle_model_subscription_connect("anthropic")
        elif operation == "complete":
            await adapter._handle_model_subscription_complete("anthropic", "code", None)
        elif operation == "ollama":
            await adapter._handle_ollama_models_get()
        elif operation == "pull":
            await adapter._handle_local_llm_pull_model("test-model")
        assert status_threads
        assert all(thread != loop_thread for thread in status_threads)
        assert all(thread == loop_thread for thread in reinit_threads)

    asyncio.run(run())
    assert sent[-1]["data"]["success"]
    if operation in ("image_rollback", "video_rollback"):
        assert len(status_threads) == 1
        assert sent[-1]["data"]["warning"]
    elif operation in ("connect", "complete"):
        assert sent[-1]["data"]["active_provider"] == "anthropic"
        assert len(reinit_threads) == 1


def test_onboarding_uses_saved_connection_without_a_cli_status_check(monkeypatch):
    from app.onboarding.interfaces.steps import ApiKeyStep
    from app.ui_layer.onboarding.controller import OnboardingFlowController

    connected(monkeypatch)
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda: pytest.fail("Blocking CLI status in onboarding"),
    )
    assert ApiKeyStep("anthropic").validate("") == (True, None)
    assert OnboardingFlowController._subscription_connected("anthropic")
    monkeypatch.setattr(claude_code, "has_credential", lambda: False)
    assert not ApiKeyStep("anthropic").validate("")[0]
    assert not OnboardingFlowController._subscription_connected("anthropic")


def test_onboarding_settings_updates_can_skip_unused_live_status(monkeypatch):
    from app.ui_layer.settings import model_settings

    connected(monkeypatch)
    monkeypatch.setattr(model_settings, "_load_settings", lambda: {})
    monkeypatch.setattr(model_settings, "_save_settings", lambda settings: True)
    monkeypatch.setattr("app.config.reload_settings", lambda: None)
    monkeypatch.setattr(
        claude_code,
        "auth_status",
        lambda: pytest.fail("Unused CLI status in onboarding"),
    )
    result = model_settings.update_model_settings(
        image_gen_provider="openai", include_subscription_status=False
    )
    assert result["success"]
    assert result["image_gen_provider"] == "openai"


@pytest.mark.parametrize(
    "checkpoint", ["existing_login", "browser_wait", "approved_login"]
)
def test_disconnect_invalidates_every_login_phase(monkeypatch, checkpoint):
    """Disconnect wins even after CLI exit or an existing-account status read."""
    from craftos_integrations.credentials_store import save_credential

    save_credential(
        claude_code.CRED_FILE,
        claude_code.ClaudeCodeConnection(profile_version=claude_code.PROFILE_VERSION),
    )
    reached = threading.Event()
    release = threading.Event()
    calls = 0
    launched = []

    def auth_status():
        nonlocal calls
        calls += 1
        current = {"connected": checkpoint == "existing_login" or calls > 1}
        if checkpoint == "existing_login" or calls > 1:
            reached.set()
            assert release.wait(5)
        return current

    def popen(args, **kwargs):
        process = FakeLogin(args, **kwargs, outcome="abandon")
        launched.append(process)
        reached.set()
        return process

    monkeypatch.setattr(claude_code, "auth_status", auth_status)
    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])
    monkeypatch.setattr(claude_code.subprocess, "Popen", popen)

    def logout(args, **kwargs):
        assert all(process.poll() is not None for process in launched)
        return SimpleNamespace(returncode=0, stdout='{"loggedIn": false}')

    monkeypatch.setattr(claude_code, "run_cli", logout)
    with ThreadPoolExecutor() as pool:
        login = pool.submit(asyncio.run, tokens.connect("anthropic"))
        try:
            assert reached.wait(5)
            if checkpoint == "approved_login":
                reached.clear()
                launched[0]._approve()
                assert reached.wait(5)
            assert tokens.disconnect("anthropic")[0]
            assert not tokens.has_credential("anthropic")
        finally:
            release.set()
        assert not login.result(timeout=5)[0]
    assert not tokens.has_credential("anthropic")
    assert claude_code._login_process is None


def test_disconnect_waits_for_pending_cli_exit_before_logout(monkeypatch):
    """Do not report success while a process can still write private auth."""
    connected(monkeypatch)
    process = SimpleNamespace(poll=lambda: None, kill=lambda: None)

    def stuck(timeout):
        raise subprocess.TimeoutExpired("claude", timeout)

    process.wait = stuck
    monkeypatch.setattr(claude_code, "_login_process", process)
    monkeypatch.setattr(
        claude_code, "run_cli", lambda *args, **kwargs: pytest.fail("CLI still running")
    )
    assert not tokens.disconnect("anthropic")[0]
    assert tokens.has_credential("anthropic")


def test_browser_disconnect_cancels_pending_login_and_reconnects_cleanly(
    monkeypatch, tmp_path
):
    """Full backend workflow: real handlers, auth facade, settings and factory."""
    from app import config
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter
    from app.ui_layer.settings import model_settings, provider_settings
    from craftos_integrations.credentials_store import save_credential

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": {"llm_provider": "anthropic"}}))
    for module in (config, model_settings, provider_settings):
        monkeypatch.setattr(module, "SETTINGS_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_settings_cache", None)
    save_credential(
        claude_code.CRED_FILE,
        claude_code.ClaudeCodeConnection(profile_version=claude_code.PROFILE_VERSION),
    )
    state = {"loggedIn": False, "authMethod": "claude.ai"}
    started = threading.Event()
    launched = []
    outcomes = iter(["abandon", "approve"])

    def signed_in():
        state["loggedIn"] = True

    def popen(args, **kwargs):
        process = FakeLogin(
            args, **kwargs, outcome=next(outcomes), on_success=signed_in
        )
        launched.append(process)
        started.set()
        return process

    def cli(args, **kwargs):
        if args == ["auth", "logout"]:
            state["loggedIn"] = False
        return SimpleNamespace(returncode=0, stdout=json.dumps(state))

    monkeypatch.setattr(claude_code, "cli_command", lambda: ["claude"])
    monkeypatch.setattr(claude_code.subprocess, "Popen", popen)
    monkeypatch.setattr(claude_code, "run_cli", cli)
    api_client = object()
    monkeypatch.setattr(
        "agent_core.core.models.factory._create_anthropic_client",
        lambda **kwargs: api_client,
    )
    clients = []
    sent = []

    def reinitialize(provider):
        context = ModelFactory.create(
            provider=provider, interface=InterfaceType.LLM, api_key="paid-key"
        )
        clients.append(context["anthropic_client"])

    async def broadcast(message):
        sent.append(message)

    adapter = object.__new__(BrowserAdapter)
    adapter._broadcast = broadcast
    adapter._controller = SimpleNamespace(
        agent=SimpleNamespace(reinitialize_llm=reinitialize)
    )

    async def run():
        pending = asyncio.create_task(
            adapter._handle_model_subscription_connect("anthropic")
        )
        assert await asyncio.to_thread(started.wait, 5)
        await adapter._handle_model_subscription_disconnect("anthropic")
        await pending
        assert not tokens.has_credential("anthropic")
        assert clients == [api_client]
        assert json.loads(path.read_text())["auth_mode"]["anthropic"] == "api_key"
        assert not next(
            message
            for message in sent
            if message["type"] == "model_subscription_connect"
        )["data"]["success"]
        await adapter._handle_model_subscription_connect("anthropic")
        assert isinstance(clients[-1], ClaudeCodeClient)
        assert tokens.has_credential("anthropic")
        assert json.loads(path.read_text())["auth_mode"]["anthropic"] == "subscription"
        await adapter._handle_model_subscription_disconnect("anthropic")
        assert clients[-1] is api_client
        assert not tokens.has_credential("anthropic")
        assert not state["loggedIn"]

    asyncio.run(run())
    assert len(launched) == 2
    assert all(process.poll() is not None for process in launched)
