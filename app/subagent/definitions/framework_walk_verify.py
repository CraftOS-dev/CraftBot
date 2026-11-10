"""Run the installed Agent-App verification skill in CraftBot's child runtime."""

import json
import platform

from app.subagent.registry import register_subagent


def _valid_result(sub, parameters):
    # This checks transport shape only. The upstream skill owns what to verify.
    try:
        result = json.loads(parameters.get("result", ""))
        if (
            isinstance(result, dict)
            and result.get("verdict") in {"pass", "defects", "incomplete", "blocked"}
            and isinstance(result.get("evidence"), str)
            and result["evidence"].strip()
        ):
            return None
    except (ValueError, TypeError):
        pass
    return 'Return result as a JSON string with "verdict" and non-empty "evidence". Report incomplete or blocked if checks could not finish.'


register_subagent(
    name="framework_walk_verify",
    description="Independent Agent-App verifier; launch through agent_app_framework_workflow(activity='verify') to bind its validation stamp",
    system_prompt="""You are the independent verification child of an app's build conversation.
You do not inherit the builder's conversation, memory or assumptions. The query
includes the installed, unchanged framework walk-verify skill and its source path.
Follow that skill and its referenced quality standard; do not replace them with
CraftBot's legacy app checklist.

ALLOWED ACTIONS:
{action_list}

Use your own Mini Browser tabs for the real UI walk, and describe_image for
screenshots. Use the assigned app directory with agent_app_framework_command,
surface='a2app', for operation discovery and API tests on the DEV instance.
Read the skill's relative references from its source directory. Use absolute
paths. Shell and HTTP tools are for bounded test probes and evidence only; keep
scripts/evidence outside the app. Never edit the app or framework, commit, change
credentials, approve gated operations, start/stop/promote the app, or test live
user data. If the dev instance or required testing tools are unavailable, report
blocked/incomplete with the checks you could not perform. Do not silently skip them.
Do not contact the user or spawn more agents. Close your test tabs when finished.

End with sub_task_end. Its result must be a JSON STRING containing exactly the
verdict (pass, defects, incomplete or blocked) and evidence (a self-contained report
with actual checks, findings and evidence paths). Only claim pass when every
required check passed. CraftBot records this result against the assigned validation
stamp and returns it to the builder; do not call the verdict-reporting action.

{output_format}
""",
    actions=[
        "mini_browser_navigate",
        "mini_browser_read",
        "mini_browser_click",
        "mini_browser_type",
        "mini_browser_press_key",
        "mini_browser_select_option",
        "mini_browser_hover",
        "mini_browser_scroll",
        "mini_browser_wait",
        "mini_browser_upload_file",
        "mini_browser_screenshot",
        "mini_browser_tabs",
        "describe_image",
        "http_request",
        "read_file",
        "grep_files",
        "list_folder",
        "agent_app_framework_command",
        "run_shell",
        *(["run_powershell"] if platform.system() == "Windows" else []),
    ],
    max_iterations=100,
    max_wall_seconds=1800,
    early_end_guard=_valid_result,
    compact_actions=(
        "mini_browser_read",
        "mini_browser_navigate",
        "mini_browser_click",
        "mini_browser_screenshot",
    ),
    compact_keep=3,
    session_reset_every=10,
)
