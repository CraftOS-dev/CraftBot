# -*- coding: utf-8 -*-
"""walk_verify — the independent "does it actually work?" gate.

A coding agent that both writes AND signs off can convince itself a compiling
shell is "done". This agent is the independent CI: it drives the RUNNING app
in a real browser against the requirements and returns a per-feature verdict.
It is READ-ONLY — it never edits code; failures go back to the build session
to fix. Spawned by ``agent_app_notify_ready`` after launch; the launch is not
"ready" until this passes. (Contract ported from PR #388.)

SCOPE (docs/design/scoped-walk-verify.md rev 2): the verifier decides which
features a change can reach and walks those. The query hands it the
symbol-level diff since the last promote, each feature's verify history and
any recorded coverage; the verifier answers with a SCOPE block — included
features, and a reason for every excluded one — before its verdicts. The
guard enforces the shape of that answer, never its content.
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

THE QUERY gives you the app URL, the project path, the requirements path,
and the EVIDENCE for deciding scope: a CHANGED SINCE LAST PROMOTE block
(what changed, attributed to functions/routes/components — with the
UNCHANGED symbols of each file listed too), LAST VERIFY RESULTS (when each
feature was last actually exercised), and, when recorded, which features
previously executed the changed code. If URL/path are missing,
sub_task_end status="failed" naming what was missing.

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
  selectors) plus agent_app_http for API checks.

YOUR WALK:
1. SCOPE — read the requirements and the CHANGED SINCE LAST PROMOTE block,
   then DECIDE which features to exercise in this walk. List every feature
   a user should be able to do (one per capability; `## Changes` entries
   are features too, the NEWEST ones being the reason this verify runs;
   ~~struck~~ entries are superseded history — skip them entirely, never
   FAIL the app for not doing them). Then choose:
   - Include every feature whose flow runs through a CHANGED function or
     route: the change itself, anything that calls a changed helper (the
     block says who references each changed symbol), anything whose data
     shape a changed migration or hook alters, anything a re-vendored kit
     or changed global style reaches. A changed FILE is not a changed
     feature: the block lists which symbols in it changed and which did
     not — scope by symbol.
   - Exclude a feature only when you can say WHY the diff cannot reach it.
   - NO BASELINE, "unavailable", a full sweep requested (VERIFY MODE:
     FULL), or a diff you cannot read → SCOPE: FULL, every feature.
   - DEFECTS TO RE-CHECK are always included. A BUILDER'S HINT is a claim,
     not evidence.
   State the decision as the FIRST section of your final result (the SCOPE
   block in OUTPUT below). Features you exclude do not appear in FEATURES.
   For included features a browser cannot exercise (scheduled emails, cron
   jobs, exports you can't download): grep_files the project's hooks for
   their implementation (a mailer call, a cronAdd for the schedule):
   implementation present → '— NOT REACHED (code present, not exercisable
   in browser)'; NO implementing code at all → FAIL — the feature was not
   built.
2. Open the app: browser_navigate to the app URL, then browser_snapshot. If
   the page is blank, an error boundary, or only skeletons, that is a FAIL for
   everything — the app doesn't run. This first-paint check is part of EVERY
   walk, however narrow the scope.
3. For EACH included feature, first call walk_mark_feature with its exact
   name (this records which code the feature runs through — the evidence
   future verifies scope with), then actually DO it with realistic data
   (browser_click / browser_type / browser_fill_form), in the order a first
   user would (onboard first, then the flows that need that state). After
   each step, snapshot and confirm the app RESPONDED: data appeared,
   navigation happened, the value updated, it persisted. "The control
   exists" is NOT working — it must DO the thing. Create test records
   without hesitation: the app you're driving is isolated from the user (a
   pre-delivery build, or a staging copy with a disposable data clone) —
   your writes never reach real data. Always use the base_url you were
   GIVEN, never a port you derive yourself.
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
   The fetch happens server-side, so the browser cannot see it — grep_files
   the project's pb/pb_hooks/*.js (excluding _*.js, the vendored bridge) for
   "$http.send", "callIntegration", "callLLM", "callAction" or "cronAdd", and
   satisfy YOURSELF that a real call is reachable from the code serving that
   feature (a match inside a comment, a string, or a function nothing calls
   is not one). Nothing present = FAIL for that feature: "displays data but
   the app fetches nothing — the data cannot be live". An "AI" feature needs
   "callLLM" or an external LLM call — string-joining records is not AI. If
   the serving hook generates values instead (Math.random, hardcoded
   samples), FAIL it and quote the line.
   How you WRITE the finding is not part of the test. NEVER mark a feature
   FAIL because of how evidence is cited or phrased — a citation is not a
   defect, and a FAIL there blocks the deploy of a working app. If you
   watched the flow work and the call is there, it is a PASS.
   This rule exists because an app once rendered Math.random() as "live
   weather" and passed review, another passed a "scheduled daily pull" whose
   hooks contained no fetch, and a third passed an "AI summary" that just
   listed the items (observed live 2026-08-06). The requirement to QUOTE the
   hook was removed on 2026-09-02, after a verifier FAILed an AI feature it
   had just watched work purely for not phrasing the quote — which blocked a
   real deploy while the user was told it had shipped.
7. DISPUTED verdicts — if your query carries a "DISPUTED BY THE BUILDER"
   block, the builder reproduced that feature and says your last verdict was
   wrong. It could run the flow repeatedly and read the server log while it
   did; you saw it once. So exercise each disputed feature yourself and
   answer the evidence: either FAIL it again citing what YOU observed THIS
   time (not last time), or change the verdict. Being contradicted is not a
   reason to dig in, and it is not a reason to fold either.
8. Decide each included feature and end.

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
V5. BUDGET: every turn's prompt begins with a TURN BUDGET line. Use what
    your scope needs — a narrow DELTA walk legitimately ends early; a FULL
    walk of a large app legitimately uses most of the budget. Conclude when
    every INCLUDED feature has real evidence, not before: a feature you
    chose to include and then left '— NOT REACHED' with no (code present…)
    or (tooling…) qualifier is a walk you did not finish, and it is
    rejected while turns remain. When the TURN BUDGET line shows the cap is
    near, deliver what you verified and mark the rest '— NOT REACHED'
    (never FAIL): honest partial coverage beats a walk that dies at the cap
    reporting nothing.

OUTPUT — end with ONE sub_task_end call, status="completed", and this in
`result` (plain text, NOT JSON):
```
SCOPE: DELTA | FULL
INCLUDED: <feature name>, <feature name>, …          (names, not numbers)
EXCLUDED:
- <feature name> — <why the diff cannot reach it>
- <feature name> — <reason>
(DELTA: name what you skipped — one blanket bullet is fine, e.g.
 "- all other features (boards, labels, checklists, …) — only Header.tsx
 changed and none of them run through it". FULL, or a DELTA where the diff
 reaches every feature: write exactly "EXCLUDED: none")
VERDICT: PASS | FAIL | BLOCKED
FEATURES:
- <feature> — PASS — <the flow you ran and what you saw>
- <feature> — FAIL — <the flow you ran and what you saw; include the exact
  failing route/URL when one was involved> | expected: <what a passing app
  would have shown/done>
- <feature> — NOT REACHED (code present, not exercisable in browser)
FAILURES (only if any FAIL):
- <feature>: <what you did, what you observed, what a correct app would do>
BLOCKED BY (only if BLOCKED):
- <what stopped you from exercising the app at all>
```
VERDICT is PASS only if EVERY included feature passed (NOT REACHED entries
mean the walk is incomplete). Use FAIL only for behaviour you observed; use
BLOCKED when you never got to observe any. There is NO "INCOMPLETE" or
"PARTIAL" verdict — an unfinished walk is FAIL with '— NOT REACHED' entries
for whatever you did not exercise.
"""


_MAX_ITERATIONS = 50
# FULL walks only: below this fraction of the budget, a partial conclusion is
# premature (the model cannot be trusted to know its own budget — observed
# live 2026-08-05, a verifier concluding at turn 15 then 8 citing "limited
# turns"). DELTA walks have no turn floor: they end when every included
# feature has evidence.
_EARLY_END_FRACTION = 0.7


def _guard_quality(result: str):
    """Verdict-quality gates that apply at ANY turn (a bad verdict is bad at
    turn 49 too; the model can always comply immediately by fixing it)."""
    import re as _re

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

    # A PASS whose OWN evidence describes the broken state.
    #
    # Observed live 2026-09-01 (newsletter_tool 3f6013ce), verbatim:
    #   "- Settings — PASS — ...the integration badges showed AI writer
    #    connected and Gmail send not connected..."
    # That was the exact defect the user had reported. The verifier looked
    # straight at it, wrote it down, and passed the feature — because the
    # checklist only asked whether the page RENDERS. It then passed the same
    # app again 14 minutes later, and the system announced it ready twice
    # while the user was saying it was broken.
    contradiction = _re.search(
        r"^-\s[^\n]*—\s*PASS\s*—[^\n]*?"
        r"\b(not connected|disconnected|not enabled|not configured|"
        r"unavailable|failed to|is missing|still shows|shows as not)"
        r"\b[^\n]*",
        result,
        _re.MULTILINE | _re.IGNORECASE,
    )
    # Escape hatch: a negative state can be the CORRECT one (nothing is
    # connected, so "not connected" is right). The verifier must be able to
    # say so and move on — an unsatisfiable guard just recreates the
    # reject -> BLOCKED -> bad-routing loop this file is trying to prevent.
    if contradiction and _re.search(
        r"is correct|correct display|is expected|expected because|by design|"
        r"matches the (backend|server|api|account)",
        contradiction.group(0),
        _re.IGNORECASE,
    ):
        contradiction = None
    if contradiction:
        return (
            "Verdict REJECTED — self-contradicting PASS: this line marks a "
            "feature PASS while its own evidence reports a broken or "
            f"negative state ('{contradiction.group(0)[:140]}'). If you "
            "OBSERVED that state, the feature is FAIL — say so. If that "
            "state is genuinely correct here, keep PASS but say why in the "
            "same line (e.g. 'no account is connected, so \"not connected\" "
            "is the correct display')."
        )
    # Live/external/scheduled/AI features: the browser cannot see a
    # server-side fetch, so a PASS whose report never mentions one anywhere
    # suggests the verifier judged it on rendered pixels alone.
    #
    # The TRIGGER is unchanged from the original guard. The MESSAGE is not:
    # it used to end "QUOTE the line in your verdict", and on 2026-09-02 a
    # verifier satisfied that by DOWNGRADING a feature it had watched work to
    # FAIL — a verdict that promotes nothing, so a working change never
    # shipped. A guard must not be satisfiable by breaking the thing it
    # guards, so this one now says what to do in both directions.
    live_pass = _re.search(
        r"^-\s[^\n]*\b(pull|sync|fetch|live|real-?time|bridge|external|"
        r"scheduled|refresh|ai|llm)\b[^\n]*—\s*PASS\b",
        result,
        _re.MULTILINE | _re.IGNORECASE,
    )
    if live_pass and not _re.search(
        r"\$http\.send|callIntegration|callLLM|callAction|cronAdd", result
    ):
        return (
            "Verdict REJECTED — a live/external/scheduled/AI-generated "
            f"feature is marked PASS ('{live_pass.group(0)[:120]}') and "
            "nothing in your report shows the app fetches or generates "
            "anything server-side. Per step 6, grep_files pb/pb_hooks/*.js "
            "(excluding _*.js) and settle it: if a real call is reachable "
            "from the code serving that feature, KEEP the PASS and say what "
            "you found; if there is none, FAIL it and say that. Do NOT fail "
            "a feature you watched work in order to clear this check."
        )
    return None


def _guard_scope(sub, result: str):
    """The SCOPE block must exist and be honest in SHAPE: a mode, reasons for
    every exclusion, DELTA only when the evidence allowed it, and evidence
    for every included feature. Its CONTENT (which features) is the
    verifier's judgment and is never second-guessed here."""
    import re as _re

    from app.agent_app.verify_scope import feature_verdicts, parse_scope

    query = str(getattr(sub, "query", "") or "")
    scope = parse_scope(result)
    if scope is None:
        return (
            "Verdict REJECTED — no SCOPE block. Your result must OPEN with "
            "'SCOPE: DELTA' or 'SCOPE: FULL', then 'INCLUDED:' (the feature "
            "names you exercised) and 'EXCLUDED:' (each skipped feature with "
            "the reason the diff cannot reach it, or 'none'). Re-send the "
            "same verdict with that block on top."
        )
    must_be_full = (
        "NO BASELINE" in query
        or "VERIFY MODE: FULL" in query
        or "treat as NO BASELINE" in query
    )
    if scope["mode"] == "DELTA" and must_be_full:
        return (
            "Verdict REJECTED — SCOPE: DELTA is not available for this walk: "
            "the query says NO BASELINE or VERIFY MODE: FULL, so every "
            "feature is in scope. Exercise the features you skipped and "
            "resubmit with SCOPE: FULL."
        )
    if scope["excluded_without_reason"]:
        bare = "; ".join(scope["excluded_without_reason"][:4])
        return (
            "Verdict REJECTED — EXCLUDED entries without a reason: "
            f"'{bare}'. Every excluded feature needs one line saying why the "
            "diff cannot reach it ('<feature> — <reason>'), one bullet per "
            "feature. If you excluded nothing, write exactly 'EXCLUDED: none'. "
            "Fix the block and resubmit the same verdict."
        )
    if scope["mode"] == "DELTA":
        verdicts = feature_verdicts(result)
        lowered = {k.lower(): v for k, v in verdicts.items()}
        missing = []
        for name in scope["included"]:
            key = name.lower()
            if any(key in k or k in key for k in lowered):
                continue
            missing.append(name)
        if missing:
            return (
                "Verdict REJECTED — INCLUDED features with no FEATURES line: "
                f"{', '.join(missing[:5])}. You chose to include them, so "
                "each needs a PASS / FAIL / NOT REACHED(qualified) line with "
                "evidence. Exercise them now, or move them to EXCLUDED with a "
                "reason."
            )
        # A DELTA walk has no turn floor — but an included feature left
        # bare NOT REACHED while turns remain is an unfinished walk.
        bare_nr = [
            k
            for k, v in verdicts.items()
            if v == "NOT REACHED"
            and not _re.search(
                rf"^-\s+{_re.escape(k)}\s*(?:—|–|:|-)\s*NOT REACHED\s*\((?:code present|tooling)",
                result,
                _re.MULTILINE | _re.IGNORECASE,
            )
        ]
        if bare_nr and sub.iterations < _MAX_ITERATIONS - 3:
            return (
                "Verdict REJECTED — included feature(s) left NOT REACHED "
                f"without a (code present…) or (tooling…) qualifier: "
                f"{', '.join(bare_nr[:5])}. Turns remain ({_MAX_ITERATIONS - sub.iterations}) "
                "— exercise them now, one flow per turn, then resubmit."
            )
    return None


def _early_end_guard(sub, parameters):
    """Veto a premature or malformed verdict (runner hook, see registry).

    Allowed to end at ANY turn: failed status (missing inputs), genuine
    tooling blockage (browser markers), a DELTA walk whose included features
    all carry evidence, and a FULL walk that is complete. A FULL walk with
    bare NOT REACHED entries before 70% of the budget is premature (the
    guard's original purpose); a DELTA walk with a missing or shapeless
    SCOPE block is rejected regardless of turn.
    """
    import re as _re

    if str(parameters.get("status") or "") != "completed":
        return None
    result = str(parameters.get("result") or "")

    rejection = _guard_quality(result)
    if rejection:
        return rejection

    # Genuine tooling blockage may conclude whenever it occurs.
    from app.agent_app.walk_verify import _reads_as_blocked

    if _reads_as_blocked(result):
        return None

    try:
        rejection = _guard_scope(sub, result)
    except Exception:
        rejection = None  # never trap the verifier on a guard bug
    if rejection:
        return rejection

    # FULL walks keep the premature-conclusion floor.
    try:
        from app.agent_app.verify_scope import parse_scope

        mode = (parse_scope(result) or {}).get("mode", "FULL")
    except Exception:
        mode = "FULL"
    if mode == "DELTA":
        return None
    if sub.iterations >= int(_MAX_ITERATIONS * _EARLY_END_FRACTION):
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
        "Independently drives a RUNNING Agent App in a real browser against "
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
        "agent_app_http",
        # Coverage boundary marker (scoped verify Phase 2).
        "walk_mark_feature",
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
    # Phase 3 — per-turn cost: a snapshot is superseded by the next one.
    # Keep the newest three in context, stub the rest, and rebuild the
    # provider session every 10 turns so the stubs actually replace the
    # cached originals.
    compact_actions=(
        "mcp_playwright-mcp_browser_snapshot",
        "mcp_playwright-mcp_browser_take_screenshot",
        "browser_probe",
    ),
    compact_keep=3,
    session_reset_every=10,
)
