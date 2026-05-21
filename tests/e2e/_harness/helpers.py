"""Generic agent-driving infrastructure for LIVE end-to-end tests.

Two public functions, both integration-agnostic:

- ``build_agent(require=[...])`` — construct the real AgentBase, skip the
  test if the LLM provider or any required integration isn't configured.
- ``run_scenario(agent, user_message, ...)`` — send a chat through the
  same entry point the CraftBot UI uses, drain the trigger queue, return
  bridge status dicts. Captures every LLM call onto
  ``agent._test_llm_calls`` for the trace logger to render afterwards.

Event-loop note
---------------

Keep boot + react + assertions inside one ``asyncio.run`` call. The
integration manager binds its async resources to the loop that
``agent.boot()`` runs on; switching loops mid-test strands the bridge
and ``react()`` silently exits early.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable

import pytest

# Module-level setup mirrors app/main.py registrations BEFORE importing AgentBase.
os.environ.setdefault("GUI_MODE_ENABLED", "False")

from agent_core import StateRegistry, ConfigRegistry  # noqa: E402
from app.state.agent_state import STATE  # noqa: E402
from app.config import (  # noqa: E402
    get_project_root,
    get_llm_provider,
    get_api_key,
    get_base_url,
    get_llm_model,
    get_vlm_provider,
    get_vlm_model,
)

StateRegistry.register(lambda: STATE)
ConfigRegistry.register_workspace_root(str(get_project_root()))

from app.agent_base import AgentBase  # noqa: E402
from craftos_integrations import get_client, list_connected  # noqa: E402

from tests.e2e._harness.trace import (  # noqa: E402
    record_action_calls,
    record_llm_calls,
)


def build_agent(*, require: list[str] | tuple[str, ...] = ()) -> AgentBase:
    """Construct ``AgentBase`` the same way ``app/main.py`` does.

    Skips the test (via ``pytest.skip``) when the LLM provider or any
    integration in ``require`` isn't configured on this host, so the same
    test file is safe to keep in the suite even on machines without those
    credentials.
    """
    provider = get_llm_provider()
    if not provider:
        pytest.skip("no LLM provider configured in settings.json")
    api_key = get_api_key(provider)
    if not api_key and provider != "remote":
        pytest.skip(f"no API key for provider {provider!r} in settings.json")
    for pid in require:
        if pid not in list_connected():
            pytest.skip(f"integration {pid!r} not connected on this host.")

    return AgentBase(
        data_dir="app/data",
        chroma_path="./chroma_db",
        llm_provider=provider,
        llm_api_key=api_key,
        llm_base_url=get_base_url(provider),
        llm_model=get_llm_model(),
        vlm_provider=get_vlm_provider(),
        vlm_model=get_vlm_model(),
        deferred_init=False,
    )


async def run_scenario(
    agent: AgentBase,
    user_message: str | None = None,
    *,
    incoming_event: dict | None = None,
    wait_for_incoming: bool = False,
    expect_no_incoming: bool = False,
    incoming_prompt: str | None = None,
    incoming_filter: Callable[[dict], bool] | None = None,
    incoming_timeout: float = 30.0,
    platform: str | None = None,
    wait_for: list[str] | tuple[str, ...] = (),
    max_iterations: int = 20,
    per_iter_timeout: float = 30.0,
    ready_timeout: float = 45.0,
) -> dict[str, dict]:
    """Run one live scenario end-to-end.

    Exactly one entry mode must be set:

      - ``user_message`` — simulate the user typing a chat. Goes through
        ``agent._handle_chat_message({"text": ...})`` — same call path
        as the CraftBot UI.
      - ``incoming_event`` — synthesize the payload an integration would
        emit and fire ``agent._handle_external_event(payload)`` directly.
        Bypasses the actual bridge listener — useful only when you want
        to test the routing rules in isolation.
      - ``wait_for_incoming`` — wait for the integration manager's real
        on-message callback to fire ``_handle_external_event``. Use this
        for true end-to-end: the test pauses until you (or someone else)
        actually send a whatsapp message that the bridge picks up. Prints
        ``incoming_prompt`` first if provided, applies ``incoming_filter``
        to ignore irrelevant inbound events, and fails after
        ``incoming_timeout`` seconds if nothing matching arrives.
      - ``expect_no_incoming`` — mirror of ``wait_for_incoming``: prompt,
        then wait the full ``incoming_timeout`` and FAIL if any matching
        event arrived (timeout = test passes). For verifying that a
        config (e.g. ``self_messages_only``) drops messages BEFORE the
        agent ever sees them.

    In all modes the runner:
      1. Boots the agent via ``agent.boot(verbose=False)`` — same setup
         ``agent.run()`` does in production (config watcher, MCP, skills,
         usage reporter, integration manager, memory processing,
         scheduler, restored-task triggers).
      2. Clears runtime state so leftover tasks from prior runs don't
         contaminate the LLM's view (does NOT wipe USER.md / MEMORY.md).
      3. Waits for each integration in ``wait_for`` to report ``ready``.
      4. Fires (or waits for) the chosen entry point.
      5. Drains the trigger queue.

    Returns ``{integration_id: status_dict}`` for every ``wait_for`` entry
    so the test can pull ``owner_phone`` / ``owner_email`` / etc.
    """
    entry_modes = sum(
        1
        for x in (
            user_message,
            incoming_event,
            wait_for_incoming or None,
            expect_no_incoming or None,
        )
        if x is not None
    )
    if entry_modes != 1:
        raise ValueError(
            "run_scenario requires exactly one of user_message, "
            "incoming_event, wait_for_incoming=True, or "
            "expect_no_incoming=True"
        )

    # If we're going to wait for the bridge to deliver a message, the
    # ``_handle_external_event`` spy MUST be installed BEFORE
    # ``agent.boot()`` runs (which internally calls
    # ``_initialize_external_libraries``). The integration manager
    # captures a bound method reference to whatever ``on_message=`` it's
    # handed at init time — replacing the attribute later doesn't update
    # what the manager calls.
    matched: asyncio.Event | None = None
    captured: list[dict] = []
    spy_kind: str | None = None  # "wait" or "silence"
    orig_handler = agent._handle_external_event

    if wait_for_incoming or expect_no_incoming:
        matched = asyncio.Event()
        spy_kind = "wait" if wait_for_incoming else "silence"

        async def _external_event_spy(payload: dict) -> None:
            if incoming_filter is None or incoming_filter(payload):
                captured.append(payload)
                if matched is not None:
                    matched.set()
            return await orig_handler(payload)

        agent._handle_external_event = _external_event_spy

    # Full production boot (mirrors what agent.run() does up to but not
    # including the UI loop). Same boot as `app/main.py` performs, so the
    # test environment matches production wiring exactly.
    await agent.boot(browser_ui=False, verbose=False)

    # Reset in-memory + persisted runtime state. Keeps USER.md / MEMORY.md.
    await agent.triggers.clear()
    agent.task_manager.reset()
    agent.state_manager.reset()
    agent.event_stream_manager.clear_all()
    try:
        from app.usage.session_storage import get_session_storage

        get_session_storage().clear_all()
    except Exception:
        pass

    async with record_llm_calls(agent), record_action_calls(agent):
        # Poll each requested integration's session status until it's ready.
        bridge_statuses: dict[str, dict] = {}
        for pid in wait_for:
            client = get_client(pid)
            if client is None:
                pytest.fail(f"integration {pid!r} client not registered")
            deadline = time.time() + ready_timeout
            while time.time() < deadline:
                try:
                    status = client.get_session_status()
                    if asyncio.iscoroutine(status):
                        status = await status
                    if isinstance(status, dict) and (
                        status.get("ready") or status.get("ok")
                    ):
                        bridge_statuses[pid] = status
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.0)
            else:
                pytest.fail(
                    f"integration {pid!r} never became ready in {ready_timeout}s."
                )

        # Production entry point — chat, synthesized external, or real
        # bridge-driven external (wait for on-message to fire).
        if user_message is not None:
            payload: dict[str, Any] = {"text": user_message}
            if platform:
                payload["platform"] = platform
            await agent._handle_chat_message(payload)
        elif incoming_event is not None:
            await agent._handle_external_event(incoming_event)
        else:
            # wait_for_incoming or expect_no_incoming. The spy was installed
            # before agent.boot() above; now we just prompt + wait + interpret.
            assert spy_kind in ("wait", "silence")
            assert matched is not None
            if incoming_prompt:
                print(f"\n{incoming_prompt}\n", flush=True)
            try:
                try:
                    await asyncio.wait_for(matched.wait(), timeout=incoming_timeout)
                except asyncio.TimeoutError:
                    if spy_kind == "wait":
                        pytest.fail(
                            f"No matching incoming event arrived within "
                            f"{incoming_timeout}s. Did you send the message?"
                        )
                    # silence + timeout = expected silence, pass through
                else:
                    if spy_kind == "silence":
                        p = captured[0]
                        pytest.fail(
                            f"Expected silence within {incoming_timeout}s but "
                            f"a matching event reached the agent: "
                            f"contact={p.get('contactName')!r}, "
                            f"body={(p.get('messageBody') or '')[:120]!r}, "
                            f"is_self_message={p.get('is_self_message')}"
                        )
            finally:
                agent._handle_external_event = orig_handler

        # Drain the trigger queue. Each react() may enqueue follow-up triggers
        # (task lifecycle) — keep pulling until the queue stays empty past a
        # short grace window.
        for _ in range(max_iterations):
            deadline = asyncio.get_event_loop().time() + 1.5
            while (
                not agent.triggers._heap and asyncio.get_event_loop().time() < deadline
            ):
                await asyncio.sleep(0.1)
            if not agent.triggers._heap:
                break
            try:
                trig = await asyncio.wait_for(
                    agent.triggers.get(), timeout=per_iter_timeout
                )
            except asyncio.TimeoutError:
                break
            await agent.react(trig)

    return bridge_statuses
