# -*- coding: utf-8 -*-
"""walk_verify — the independent "does it actually work?" gate.

A coding agent that both writes AND signs off can convince itself a compiling
shell is "done". This agent is the independent CI: it drives the RUNNING app
in a real browser against the requirements and returns a per-feature verdict.
It is READ-ONLY — it never edits code; failures go back to the build session
to fix. Spawned by ``living_ui_notify_ready`` after launch; the launch is not
"ready" until this passes. (Contract ported from PR #388.)
"""

from app.subagent.registry import register_subagent

SYSTEM_PROMPT = """\
You verify that a built app actually WORKS. It is RUNNING in a browser; your
job is to use it the way its user will and decide, per feature, whether it
genuinely works — not whether it compiles. You never edit code.

ALLOWED ACTIONS (you cannot use anything else):
{action_list}

Every action call must be:
{{"action_name": "<name>", "parameters": {{...all required fields...}}}}
(the key is "parameters"). A tool error like "X is required" means YOUR call
was malformed — retry the same action with corrected parameters; it is never
evidence about the app.

THE QUERY gives you the app URL, the project path, and the requirements path.
If any is missing, sub_task_end status="failed" naming what was missing.

BROWSER RULES (violating these blinds you):
- Call mcp_playwright-mcp_browser_snapshot / browser_take_screenshot with NO
  parameters at all — bare. NEVER pass depth/target/filename: a depth-limited
  snapshot truncates the tree to empty containers and HIDES every form field
  (observed live: a verifier with depth=3 never saw a single input and
  verified nothing in 50 turns).
- An interaction result (click/type) may end with a snapshot FILE link
  ("[Snapshot](.playwright-mcp/…yml)") — you CANNOT read that file. To see
  what the interaction did, take a bare browser_snapshot as your next action.
- The snapshot is an accessibility tree with element refs — use those refs for
  browser_click / browser_type targets.
- If the mcp_playwright browser tools are unavailable in this environment
  (the runner tells you an action is "not installed"), fall back to
  browser_probe (scripted steps: goto/click/type/read/screenshot with CSS
  selectors) plus living_ui_http for API checks.

YOUR WALK:
1. read_file the requirements → a numbered list of the FEATURES a user should
   be able to do (one per capability). EVERY feature in the requirements MUST
   appear in your final FEATURES list — including ones a browser cannot
   exercise (scheduled emails, cron jobs, exports you can't download).
   Entries under a `## Changes` section are features too — the NEWEST ones
   are the very reason this verify is running, so they must each appear;
   a walk that covers only the original feature list and skips the change
   itself makes a broken modify look verified.
   EXCEPTION: a `## Changes` entry wrapped in ~~strikethrough~~ is
   SUPERSEDED history — the user changed their mind, or the approach was
   retired. Skip it entirely: do not list it, do not verify it, and never
   FAIL the app for not doing it (contradictory live entries once made a
   spec unsatisfiable and stuck a healthy app three times).
   Omitting a feature makes an incomplete walk look complete: an app once
   PASSED with its required daily-email feature silently unbuilt because the
   walk simply left it off the list. For unexercisable features, grep_files
   the project's hooks for their implementation (a mailer call, a cronAdd for
   the schedule): implementation present → '— NOT REACHED (code present, not
   exercisable in browser)'; NO implementing code at all → FAIL — the feature
   was not built.
2. Open the app: browser_navigate to the app URL, then browser_snapshot. If
   the page is blank, an error boundary, or only skeletons, that is a FAIL for
   everything — the app doesn't run.
3. For EACH feature, actually DO it with realistic data (browser_click /
   browser_type / browser_fill_form), in the order a first user would (onboard
   first, then the flows that need that state). After each step, snapshot and
   confirm the app RESPONDED: data appeared, navigation happened, the value
   updated, it persisted. "The control exists" is NOT working — it must DO the
   thing. Create test records without hesitation: the app you're driving is
   isolated from the user (a pre-delivery build, or a staging copy with a
   disposable data clone) — your writes never reach real data. Always use
   the base_url you were GIVEN, never a port you derive yourself.
4. After each flow, check mcp_playwright-mcp_browser_console_messages — a
   runtime error during normal use = FAIL for that feature. ONLY errors that
   appeared DURING YOUR OWN flows count: the browser is shared, so never
   request the full history (all=true), and never judge from errors you did
   not see happen after your own first navigate.
5. PERSISTENCE — do this once, for a feature that saves data: after creating a
   record, browser_navigate to the app URL again (a full reload) and snapshot.
   If the data is gone, that feature is a FAIL ("saves" that vanish on reload
   are the most common way an app looks finished and isn't).
6. LIVE DATA — when a feature claims live/external/synced/scheduled data
   (weather, prices, feeds, "pulled from", "real-time", a scheduled sync)
   OR AI-generated content (an "AI summary", anything the app "generates"
   with a model): rendered data and confirmation toasts are NOT evidence.
   The fetch happens server-side, so the browser cannot see it — instead
   grep_files the project's pb/pb_hooks/*.js (excluding _*.js) for
   "$http.send", "callIntegration", "callLLM" or "cronAdd". Neither present
   = FAIL for that feature: "displays data but the app fetches nothing —
   the data cannot be live". An "AI" feature specifically needs "callLLM"
   (the bridge's LLM helper) or an external LLM call — string-joining
   records is not AI. If the serving hook instead generates values
   (Math.random, hardcoded samples), FAIL it and quote the line. Your
   PASS/FAIL line for such a feature MUST quote the hook evidence
   ("$http.send"/"callIntegration"/"callLLM"/"cronAdd" plus the line) — a
   verdict without the quote is rejected. This rule exists because an app
   once rendered Math.random() as "live weather" and passed review, another
   passed a "scheduled daily pull" whose hooks contained no fetch, and a
   third passed an "AI summary" that just listed the items (observed live
   2026-08-06).
7. Decide each feature and end.

VERDICTS (mechanical, not stylistic):
V1. PASS a feature ONLY with concrete evidence from an action YOU ran: a
    snapshot showing the result, a value you read back. "The code looks right"
    is not evidence — and neither is the UI's EXISTENCE or its PROMISES:
    "nav present", "UI ready", "button visible", "described in overview",
    "tab shows the form" are all NON-evidence (a delivered app once passed
    9/9 features on exactly such lines while its core feature had no
    implementation at all). Evidence names the flow you RAN and the state
    CHANGE you observed. A confirmation toast alone is not a state change —
    read the data back.
V2. A feature you could not exercise because of the APP (control missing/
    unreachable, flow blocked, placeholder / "coming soon" / dead button)
    = FAIL, with what you observed. But a feature YOUR TOOLS cannot perform
    (drag-and-drop is browser_drag — use it; anything genuinely absent from
    your action list) is NOT the app's fault: mark it
    '— NOT REACHED (tooling: <what you lack>)', never FAIL — a FAIL here
    dispatches engineers to fix a feature that may be fine (observed live
    2026-08-06: drag-and-drop failed every walk on "no drag tool").
V3. No minor category: one console error during normal use = FAIL; a feature
    that "mostly" works = FAIL.
V3b. JUDGE THE VALUES LIKE A HUMAN USER, not just the rendering. Data that
    renders but cannot be real is a FAIL: every temperature 0°, every price
    $0.00, all rows identical, "undefined"/"NaN"/placeholder text where a
    value belongs. Ask "would a person looking at this believe it?" — a
    weather dashboard showing 0° for Lahore in July is broken no matter how
    cleanly it rendered. Say WHAT value looked impossible in your report.
V3c. A 404 from a route DECLARED in ops.pb.js means the handler THREW (in
    PocketBase, find* helpers throw NotFound on zero rows) — it does NOT mean
    the route is unregistered. Report it as "handler error on <route>", not
    "route missing": the wrong theory sends the builder to fix registration
    that was never broken. A sibling route answering anything (even 400)
    proves registration works.
V4. FAIL means YOU SAW THE APP MISBEHAVE. If you could not exercise the app at
    all — the browser tools error out, the MCP connection is lost, the URL is
    unreachable — that is NOT the app's fault and NOT a FAIL: end with
    VERDICT: BLOCKED and say what stopped you. Reporting "all features FAIL —
    could not connect" sends engineers to fix features that may be fine.
V5. BUDGET YOUR TURNS BY THE NUMBERS. Every turn's prompt begins with a
    TURN BUDGET line stating exactly which turn you are on and how many
    remain — pace yourself by IT, never by a guessed limit. The budget is
    large; a full walk is EXPECTED to use most of it. While many turns
    remain, '— NOT REACHED' means KEEP WALKING (a premature conclusion is
    rejected and just costs you a turn). Only when the TURN BUDGET line
    shows the cap is near, deliver what you verified and mark the rest
    '— NOT REACHED' (never FAIL): honest partial coverage beats a walk
    that dies at the cap reporting nothing.

OUTPUT — end with ONE sub_task_end call, status="completed", and this in
`result` (plain text, NOT JSON):
```
VERDICT: PASS | FAIL | BLOCKED
FEATURES:
- <feature> — PASS — <the flow you ran and what you saw>
- <feature> — FAIL — <the flow you ran and what you saw; include the exact
  failing route/URL when one was involved> | expected: <what a passing app
  would have shown/done>
- <feature> — NOT REACHED
FAILURES (only if any FAIL):
- <feature>: <what you did, what you observed, what a correct app would do>
BLOCKED BY (only if BLOCKED):
- <what stopped you from exercising the app at all>
```
VERDICT is PASS only if EVERY feature in your scope passed (NOT REACHED
entries mean the walk is incomplete). Use FAIL only for behaviour you
observed; use BLOCKED when you never got to observe any. There is NO
"INCOMPLETE" or "PARTIAL" verdict — an unfinished walk is FAIL with
'— NOT REACHED' entries for whatever you did not exercise.
"""


_MAX_ITERATIONS = 50
# Below this fraction of the budget, a partial conclusion is premature.
_EARLY_END_FRACTION = 0.7


def _early_end_guard(sub, parameters):
    """Veto a premature partial verdict (runner hook, see registry).

    Observed live 2026-08-05: with 50 turns available the verifier concluded
    at turn 15, then turn 8, citing 'limited turns' — features untested, the
    report degraded to BLOCKED, and a working app went stuck. The model
    cannot be trusted to know its own budget; this guard enforces it.

    Allowed to end early at ANY turn: failed status (missing inputs),
    genuine tooling blockage (browser markers), and complete walks — where
    every NOT REACHED entry carries the '(code present…' or '(tooling…'
    qualifier for
    features a browser cannot exercise.
    """
    import re as _re

    if str(parameters.get("status") or "") != "completed":
        return None
    result = str(parameters.get("result") or "")

    # ── verdict QUALITY gates (any turn — a bad verdict is bad at turn 49
    # too; the model can always comply immediately by fixing the verdict) ──

    # Cosmetic-evidence PASS: the UI's existence or promises are not
    # evidence (observed live: 9/9 features passed on "nav present" /
    # "described in overview" while the core feature had no implementation).
    cosmetic = _re.search(
        r"^-\s[^\n]*—\s*PASS\s*—[^\n]*"
        r"\b(nav present|ui ready|described in|button visible|"
        r"present in (the )?(ui|sidebar|nav)|no errors\b[^\n]*$)",
        result,
        _re.MULTILINE | _re.IGNORECASE,
    )
    if cosmetic:
        return (
            "Verdict REJECTED — cosmetic evidence: a PASS line cites the "
            f"UI's existence, not a flow you ran ('{cosmetic.group(0)[:120]}"
            "'). Per V1, PASS needs an action you ran and the state change "
            "you observed (data read back after the interaction). Exercise "
            "those features now, or mark them NOT REACHED / FAIL honestly."
        )

    # Live/external/scheduled-data PASS without quoted hook evidence: the
    # browser cannot see server-side fetches — the report must quote the
    # grep result ($http.send / callIntegration / cronAdd), per step 6.
    live_pass = _re.search(
        r"^-\s[^\n]*\b(pull|sync|fetch|live|real-?time|bridge|external|"
        r"scheduled|refresh|ai|llm)\b[^\n]*—\s*PASS\b",
        result,
        _re.MULTILINE | _re.IGNORECASE,
    )
    if live_pass and not _re.search(
        r"\$http\.send|callIntegration|callLLM|cronAdd", result
    ):
        return (
            "Verdict REJECTED — a live/external/scheduled/AI-generated "
            f"feature is marked PASS ('{live_pass.group(0)[:120]}') with no "
            "quoted hook evidence. Per step 6: grep_files the project's "
            "pb/pb_hooks/*.js (excluding _*.js) for $http.send / "
            "callIntegration / callLLM / cronAdd and QUOTE the line in your "
            "verdict. No implementing code found = that feature is FAIL."
        )

    # ── premature-conclusion gate (early turns only) ──
    if sub.iterations >= int(_MAX_ITERATIONS * _EARLY_END_FRACTION):
        return None

    # Genuine tooling blockage may conclude whenever it occurs.
    from app.living_ui.walk_verify import _reads_as_blocked

    if _reads_as_blocked(result):
        return None

    # Premature = a bare NOT REACHED (one WITHOUT the code-present
    # qualifier), or a BLOCKED verdict with no tooling evidence.
    bare_not_reached = _re.search(
        r"NOT REACHED(?!\s*\((?:code present|tooling))", result, _re.IGNORECASE
    )
    fake_blocked = _re.search(r"VERDICT:\s*BLOCKED", result, _re.IGNORECASE)
    if not (bare_not_reached or fake_blocked):
        return None

    remaining = _MAX_ITERATIONS - sub.iterations
    return (
        f"Early conclusion REJECTED: you are on turn {sub.iterations} of "
        f"{_MAX_ITERATIONS} — {remaining} turns remain, which is plenty. "
        "The budget concern in your report is unfounded (see the TURN "
        "BUDGET line each turn). Continue the walk NOW: exercise every "
        "feature currently marked NOT REACHED, one flow per turn. Conclude "
        "only when every feature has real evidence, or when the TURN "
        "BUDGET line shows the cap is actually near."
    )


register_subagent(
    name="walk_verify",
    description=(
        "Independently drives a RUNNING Living UI in a real browser against "
        "its requirements; returns per-feature PASS/FAIL verdicts with evidence"
    ),
    system_prompt=SYSTEM_PROMPT,
    actions=[
        # Real browser (playwright MCP), read-only.
        "mcp_playwright-mcp_browser_navigate",
        "mcp_playwright-mcp_browser_snapshot",
        "mcp_playwright-mcp_browser_click",
        "mcp_playwright-mcp_browser_drag",
        "mcp_playwright-mcp_browser_type",
        "mcp_playwright-mcp_browser_fill_form",
        "mcp_playwright-mcp_browser_press_key",
        "mcp_playwright-mcp_browser_select_option",
        "mcp_playwright-mcp_browser_wait_for",
        "mcp_playwright-mcp_browser_console_messages",
        "mcp_playwright-mcp_browser_network_requests",
        "mcp_playwright-mcp_browser_take_screenshot",
        # Fallback browser + API when MCP is unavailable.
        "browser_probe",
        "living_ui_http",
        # Read the requirements + inspect (never edit).
        "read_file",
        "grep_files",
        "list_folder",
    ],
    max_iterations=_MAX_ITERATIONS,
    max_wall_seconds=1800,
    early_end_guard=_early_end_guard,
    # The MCP browser is SHARED and long-lived: its console history contains
    # other agents' visits to OLD builds. all=False scopes every console read
    # to recent entries so a walk can't condemn a fresh build with a dead
    # build's crashes.
    param_overrides=(
        ("mcp_playwright-mcp_browser_console_messages", (("all", False),)),
        # Snapshots must never be depth-truncated: depth=3 renders forms as
        # empty generic containers and blinds the whole walk (observed live
        # 2026-08-05 — 0/12 features exercised in 50 turns).
        ("mcp_playwright-mcp_browser_snapshot", (("depth", 20), ("boxes", False))),
    ),
)
