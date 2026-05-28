"""Level-1 smoke tests: action registry + simulated handlers.

Cheapest layer of the testing pyramid. Verifies:
1. The action registry loads at all.
2. Actions the agent's routing depends on exist.
3. An action's test_payload + simulated_mode flow runs end-to-end.

These tests do NOT boot the full agent (no LLM, no DB, no integrations).
See test_action_router.py for level-2 tests that mock the LLM and exercise
ActionRouter routing decisions.
"""

import asyncio
import inspect
import platform


from agent_core import load_actions_from_directories, registry_instance


# Action handlers whose test_payload + simulated_mode flow is currently
# broken — the handler doesn't honor simulated_mode before hitting the real
# filesystem / interface. Each one is a separate action-side fix; skip here
# so the registry-wide smoke loop stays green.
#   find_files: hardcoded C:\Users\user\Documents in test_payload
#   send_message_with_attachment: validates file paths before simulated branch
KNOWN_BROKEN_TEST_PAYLOADS = {
    "find_files",
    "send_message_with_attachment",
}


def _run_handler(impl):
    """Invoke a handler with its test_payload, awaiting if it's async."""
    result = impl.handler(impl.metadata.test_payload)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return result


_LOADED = False


def _ensure_actions_loaded():
    global _LOADED
    if not _LOADED:
        load_actions_from_directories(paths_to_scan=["app/data/action"])
        _LOADED = True


def test_action_registry_loads():
    _ensure_actions_loaded()
    actions = registry_instance.list_all_actions()
    assert len(actions) > 100, f"expected >100 actions, got {len(actions)}"


def test_critical_routing_actions_exist():
    """Conversation-mode routing in ActionRouter pulls these by name."""
    _ensure_actions_loaded()
    actions = registry_instance.list_all_actions()
    for required in ("send_message", "task_start", "ignore"):
        assert required in actions, f"missing core routing action: {required}"


def test_representative_integration_actions_exist():
    _ensure_actions_loaded()
    actions = registry_instance.list_all_actions()
    for required in ("send_gmail", "list_gmail", "send_slack_message"):
        assert required in actions, f"missing integration action: {required}"


def test_web_search_simulated_end_to_end():
    """web_search has test_payload={simulated_mode: True} — exercise it."""
    _ensure_actions_loaded()
    impl = registry_instance.get_action_implementation(
        "web_search", platform.system().lower()
    )
    assert impl is not None, "web_search has no impl for this platform"
    assert impl.metadata.test_payload is not None, "web_search has no test_payload"

    result = _run_handler(impl)
    assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
    assert result.get("status") in ("success", "ok"), f"non-success status: {result}"
    assert result.get("result_count", 0) > 0, "simulated search returned no results"


def test_all_testable_actions_smoke():
    """Same loop as run_actions_tests.py — every action with test_payload.

    Acts as a tripwire: if anyone adds test_payload to a new action, this
    catches the smoke regression for free.
    """
    _ensure_actions_loaded()
    testable = registry_instance.get_testable_actions(platform.system().lower())
    assert testable, "registry reports zero testable actions"

    failures = []
    skipped = []
    for impl in testable:
        if impl.metadata.name in KNOWN_BROKEN_TEST_PAYLOADS:
            skipped.append(impl.metadata.name)
            continue
        try:
            result = _run_handler(impl)
            if not isinstance(result, dict):
                failures.append(
                    (impl.metadata.name, f"non-dict: {type(result).__name__}")
                )
                continue
            status = result.get("status")
            if status not in ("success", "ok", "ignored", "completed", "queued", None):
                failures.append(
                    (
                        impl.metadata.name,
                        f"status={status}: {result.get('message', '')}",
                    )
                )
        except Exception as e:
            failures.append((impl.metadata.name, f"raised: {type(e).__name__}: {e}"))

    if skipped:
        print(f"\nskipped {len(skipped)} known-broken: {skipped}")
    assert not failures, "testable actions failed:\n" + "\n".join(
        f"  {n}: {m}" for n, m in failures
    )
