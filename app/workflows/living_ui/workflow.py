# -*- coding: utf-8 -*-
"""Living UI development — ONE class: the domain's prompts + its step program.

Runtime shape — ``Task → steps workflow → actions``: a development task
(create, update, fix, resume — the loop is the same) carries
``workflow_id="living_ui_development"`` and resolves this class's
registered instance; its inherited
:meth:`~app.workflows.workflow.Workflow.step` drives every
turn — scaffold (the model's one build duty) → coding_agent work rounds →
independent walk_verify check → present/end. The model gets a decision turn
only for the scaffold and for "llm" talk steps, each arriving as a
``<step_directive>`` block in THAT turn's prompt.

Variants: subclass, override a stage / query / prompt method (they are all
overridable — see Workflow), give the class a new ``name``, and
register an instance.
"""

from pathlib import Path
from typing import Any, Optional

# THE workflow id development tasks carry. "living_ui_creation" is the
# pre-rename legacy id, kept as a registry alias so persisted tasks from
# before the rename still resolve after a restart.
WORKFLOW_ID = "living_ui_development"
LEGACY_WORKFLOW_ID = "living_ui_creation"

from agent_core.core.registry.task_workflows import register_workflow

from app.workflows.living_ui.steps import (
    FIX_ROUND_BUDGET,
    WALK_ATTEMPT_BUDGET,
    BuildState,
    fixlog_backfill_outcome,
    fixlog_block,
    fixlog_excerpt,
    leads_block,
)
from app.workflows.workflow import StepContext, Workflow

SYSTEM_PROMPT = """\
You are CraftBot's Living UI creator. The PLATFORM builds the app — a
coding agent writes and fixes the code, and the platform builds, launches,
and tracks progress. YOU are its voice and its bootstrap. Your duties:

1. BOOTSTRAP: if the task has no project yet, attach one — then send the
   user ONE short kickoff message; the platform drives everything after.
   - Task about an EXISTING app (updating, fixing, or continuing one the
     user already has)? NEVER scaffold a duplicate: find it (`livingui ls`
     via run_shell) and living_ui_adopt(project_id, change_request).
   - Genuinely NEW app → living_ui_scaffold(name, description, ...) from
     the task requirements.
2. OBEY STEP DIRECTIVES: when a turn contains a <step_directive> block, it
   IS your instruction for this turn — do exactly what it says with the
   allowed actions, nothing else.

TALKING TO THE USER (your main craft):
- Brief, warm, honest. No play-by-play narration.
- NEVER mention internal machinery: directives, budgets, build rounds,
  retries, sub-agents, the build pipeline.
- NEVER claim something works that the build hasn't passed; never seed
  fake data to look done.
- When asked to WAIT for a reply (wait_for_user_reply=true), wait — the
  platform reads their answer and continues the build.
- When presenting the finished app: short and concrete — what it does,
  where it is, invite them to try it.

If the user reports a problem after launch: get evidence first
(`livingui <project_id> logs --tail 100`), then spawn a coding_agent to
reproduce it, fix the code, and re-build before replying. The user is
never your test harness.

Platform facts: the stack is Vite + React + TypeScript + Tailwind with
shadcn/ui components already in the project. The coding agent owns and
edits ALL the code; the build (npm run build) is the source of truth.
Deeper how-tos: skills/living-ui-creator/references/.
"""


# Replaces SELECT_ACTION_IN_TASK_PROMPT for this workflow. Same format
# variables; the <output_format> block is copied VERBATIM from
# agent_core/core/prompts/action.py — the decision parser depends on it.
CONDUCTOR_ACTION_PROMPT = """\
<rules>
You are the voice of a platform-driven Living UI build. Decision order:
1. A <step_directive> block in this turn's input is your instruction —
   follow it exactly, using only the actions it allows.
2. No directive and no project attached to THIS task yet → attach one,
   plus ONE short kickoff send_message:
   - about an EXISTING app (update/fix/continue) → find it (`livingui ls`)
     and living_ui_adopt(project_id, change_request) — never scaffold a
     duplicate of an app the user already has;
   - genuinely new app → living_ui_scaffold from the task requirements.
3. No directive and the project is attached → the platform is building;
   just wait (or answer the user briefly if they wrote).
Never: invent build steps, re-run the build "to check", edit app code
yourself, spawn agents no directive named, touch the todo list (the
platform manages it), or end the task before the app was presented.
</rules>

<output_format>
Return ONLY a valid JSON object with this structure and no extra commentary:
{{
  "reasoning": "<chain-of-thought about current todo, its phase, completion status, and decision>",
  "actions": [
    {{
      "action_name": "<name of the chosen action>",
      "parameters": {{
        "<parameter name>": <value>
      }}
    }}
  ]
}}

For parallel actions, include multiple entries in the "actions" array.
For a single action, use an array with one entry.

Example (single action):
{{
  "reasoning": "The user asked how the build is going; answering briefly",
  "actions": [
    {{"action_name": "send_message", "parameters": {{"message": "..."}}}}
  ]
}}

Example (parallel actions):
{{
  "reasoning": "Need to read two config files to understand the setup",
  "actions": [
    {{"action_name": "read_file", "parameters": {{"path": "config.json"}}}},
    {{"action_name": "read_file", "parameters": {{"path": "settings.yaml"}}}}
  ]
}}
</output_format>

<actions>
{action_candidates}
</actions>

{task_state}

<objective>
{query}
</objective>

---

{event_stream}

{integration_essentials}
"""


class LivingUIWorkflow(Workflow):
    """The Living UI build: coding_agent works, walk_verify checks, the
    launch pipeline stages, PocketBase persists. One class = the task's
    prompt dressing AND its deterministic step program."""

    # Task surface
    name = WORKFLOW_ID
    description = (
        "Living UI development task: step-driven build/update (code "
        "decides, the LLM talks). Skills/essentials/memory injections "
        "off; generic task protocol replaced."
    )
    system_prompt = SYSTEM_PROMPT
    select_action_prompt = CONDUCTOR_ACTION_PROMPT

    # Engine surface
    worker_agent = "coding_agent"
    checker_agent = "walk_verify"
    stage_action = "living_ui_validate"  # build + launch the app
    notify_action = "living_ui_notify_ready"
    round_budget = FIX_ROUND_BUDGET
    check_attempt_budget = WALK_ATTEMPT_BUDGET
    state_class = BuildState
    work_label = "Building the app (round {round} of {budget})."
    check_label = "Checking every feature works (round {round})."

    # ── domain hooks ─────────────────────────────────────────────────────────
    def resolve_subject(self, task: Any) -> Optional[Any]:
        """The task's Living UI project, via the manager singleton."""
        from app.living_ui._state import get_living_ui_manager

        manager = get_living_ui_manager()
        if manager is None:
            return None
        return next(
            (
                p
                for p in manager.projects.values()
                if getattr(p, "task_id", None) == getattr(task, "id", None)
            ),
            None,
        )

    def state_dir(self, subject: Any) -> Path:
        return Path(subject.path)

    def is_bootstrapped(self, ctx: StepContext) -> bool:
        """The scaffold has been copied once frontend/App.tsx exists."""
        return (ctx.state_dir / "frontend" / "App.tsx").exists()

    def on_turn(self, ctx: StepContext) -> None:
        from app.workflows.living_ui.steps import sync_todos

        sync_todos(ctx.task, ctx.subject, ctx.state)

    def describe_subject(self, ctx: StepContext) -> str:
        name = getattr(ctx.subject, "name", "") or ctx.subject.id
        return f"their app ({name})"

    def stage_action_params(self, ctx: StepContext) -> dict:
        return {"project_id": str(ctx.subject.id)}

    def notify_params(self, ctx: StepContext) -> dict:
        return {"project_id": str(ctx.subject.id)}

    def on_verified(self, state_dir: Path) -> None:
        """Set the manager's validation_passed_at (the task_end gate) once
        the walk confirms the app works. Fail-open."""
        try:
            import time as _t

            from app.living_ui._state import get_living_ui_manager

            manager = get_living_ui_manager()
            if manager is None:
                return
            for p in manager.projects.values():
                if str(getattr(p, "path", "")) == str(state_dir):
                    p.validation_passed_at = _t.time()
                    break
        except Exception:
            pass

    def on_work_failed(self, state_dir: Path, step: str) -> None:
        if step:
            fixlog_backfill_outcome(
                state_dir, "VALIDATE", f"build/launch failed again at step {step}"
            )

    def on_check_failed(self, state_dir: Path) -> None:
        fixlog_backfill_outcome(
            state_dir, "VALIDATE", "features still not working at the walk"
        )

    # ── queries ──────────────────────────────────────────────────────────────
    def work_query(self, ctx: StepContext) -> str:
        """The coding_agent's brief: project path + the running app URL +
        what to build. It owns the whole repo and loops until every feature
        actually works."""
        project = ctx.subject
        reqs = ctx.state_dir / "reference" / "requirements.md"
        app_url = getattr(project, "dev_url", "") or getattr(project, "url", "") or ""
        head = (
            f"Project ID: {project.id}\n"
            f"Project Path: {project.path}\n"
            f"(run `livingui {project.id} status` for URLs, "
            f"`livingui {project.id} logs --tail 60` for logs)\n"
            f"App URL (Vite dev server, hot-reloads on save): {app_url}\n"
        )
        if ctx.state.update_scope:
            # TARGETED UPDATE: the change is the job — not a rebuild.
            q = head + (
                "This is a TARGETED UPDATE to a working app. Make ONLY the "
                "requested change(s) — see USER'S CHANGE REQUESTS below. Do "
                "NOT refactor, rebuild, or 'improve' unrelated code; touch "
                "the fewest files that do the job. verify_build proves it "
                "compiles; verify YOUR CHANGE works in the browser before "
                "ending. Requirements (context only): "
                + (f"{reqs}" if reqs.exists() else f"(see {ctx.state_dir}/reference/)")
            )
        else:
            q = head + (
                "Build this app so every feature actually WORKS. Requirements: "
                + (f"{reqs}" if reqs.exists() else f"(see {ctx.state_dir}/reference/)")
                + "\nWork feature by feature; verify_build proves it compiles, the "
                "browser proves it works; finish only when every feature works live."
            )
        # A failed build/launch pipeline is THE current blocker — hand the
        # agent the pipeline's own diagnosis verbatim (session 20260717115332:
        # PocketBase's exact rejection sat unread in last_result while the
        # next agent chased a stale lead and rediscovered it by hand).
        last = ctx.state.last_result or {}
        if last.get("step") not in (None, "", "success") and last.get("errors"):
            q += (
                f"\n\nThe last build/launch attempt FAILED at step "
                f"'{last['step']}'. These errors are the CURRENT blocker — "
                "fix them before anything else:\n"
            )
            q += "\n".join(f"- {e}" for e in last["errors"][:6])
        # A prior walk's observed gaps are this round's work order.
        broken = ctx.state.check_failures
        if broken:
            q += "\n\nThe last check found these features NOT working — fix them first:\n"
            q += "\n".join(f"- {t}" for t in broken[:8])
        q += leads_block(ctx.state_dir, self.state_class)
        q += fixlog_block(ctx.state_dir, "VALIDATE")
        return q

    def check_query(self, ctx: StepContext) -> str:
        """The walk_verify brief: where the running app is + where the
        requirements are + the coverage scope (features already verified
        this phase are skipped, so capped walks ACCUMULATE instead of each
        one restarting from feature 1). It never edits code."""
        project = ctx.subject
        reqs = ctx.state_dir / "reference" / "requirements.md"
        app_url = getattr(project, "url", "") or getattr(project, "dev_url", "") or ""

        # TARGETED UPDATE + frontend-only writes → verify the change + a
        # smoke pass, not the whole app (a sidebar color fix must not cost
        # a 172-action full walk). Backend/config/tests writes have wide
        # blast radius → full rigor regardless of scope.
        if ctx.state.update_scope and set(ctx.state.touched_areas or []) <= {
            "frontend"
        }:
            change = "\n".join(
                f"  - {lead}" for lead in (ctx.state.user_leads or [])[-3:]
            ) or "  (see the task's change request)"
            return (
                f"App URL (running app): {app_url}\n"
                f"Project Path: {project.path}\n"
                "TARGETED CHECK — a small frontend change was made to a "
                "previously verified app. Verify TWO things only:\n"
                f"1. THE CHANGE works as requested:\n{change}\n"
                "2. SMOKE: the app loads, main navigation works, and the "
                "browser console shows ZERO errors during it.\n"
                "Do NOT walk every feature. End with VERDICT: PASS|FAIL and "
                "one line per item ('- <item> — PASS' / '- <item> — FAIL: "
                "<what you observed>'). PASS only if the change works AND "
                "the smoke pass is clean."
            )

        scope = ""
        if ctx.state.checked_ok:
            done = "\n".join(f"  - {f}" for f in ctx.state.checked_ok)
            scope = (
                "\nALREADY VERIFIED this phase — do NOT re-verify (a quick "
                f"smoke at most if your path crosses them):\n{done}\n"
                "Verify the REMAINING features (everything in the "
                "requirements NOT listed above), starting with them "
                "immediately.\n"
            )
        return (
            f"App URL (running app): {app_url}\n"
            f"Project Path: {project.path}\n"
            f"Requirements: {reqs if reqs.exists() else ctx.state_dir / 'reference'}\n"
            f"{scope}"
            "Verify EVERY feature in the requirements actually works by using it in "
            "the browser. End with VERDICT: PASS|FAIL and a per-feature list "
            "(one line each: '- <feature> — PASS' or '- <feature> — FAIL: "
            "<what you observed>'). Features you did not get to: '- <feature> "
            "— NOT REACHED' (never FAIL). PASS only if every feature in your "
            "scope works."
        )

    def spawn_context(self, ctx: StepContext) -> dict:
        """Structured routing id for every spawn: the outcome tap
        (construction_events._record_specialist_spawn) resolves the project
        from this instead of regex-scraping the query text.

        DELIBERATELY does not call super(): omitting the generic routing
        keys opts this domain OUT of the generic outcome tap — Living UI's
        outcomes flow through its own taps (construction_events + the
        launch pipeline), and double-recording would corrupt the loop."""
        return {"project_id": ctx.subject.id}

    # ── talk-duty prompts ────────────────────────────────────────────────────
    # answer_user_prompt / budget_gate_prompt come from the base class;
    # the domain contributes only the fix-ledger evidence below.
    def budget_gate_tried_block(self, ctx: StepContext) -> str:
        return fixlog_excerpt(ctx.state_dir, "VALIDATE")

    def presentation_prompt(self, ctx: StepContext) -> str:
        base = (
            f"The app ({getattr(ctx.subject, 'name', '') or ctx.subject.id}) is "
            "built, verified end-to-end in a real browser, and already presented "
            "on screen. In ONE decision: send_message the user a short, warm "
            "presentation (what the app does, invite them to try it — 2-4 "
            'sentences), AND call task_end(status="complete", reason, summary) '
            "in the same actions list."
        )
        backlog = (ctx.state.backlog or [])[-3:]
        if backlog:
            items = "; ".join(b[:120] for b in backlog)
            base += (
                " ALSO: earlier requests were never finished — mention them "
                f"briefly (paraphrase, don't quote verbatim): {items}. Ask in "
                "the SAME message whether they'd like you to continue with "
                "any of these — do NOT start them yourself."
            )
        return base + f" {self._TALK_RULES}"

    def end_step(self, ctx: StepContext) -> dict:
        return {
            "kind": "end",
            "status": "complete",
            "label": "Build complete.",
            "reason": "The app was built and passed validation including the browser walk.",
            "summary": (
                f"Built Living UI project {ctx.subject.id} "
                f"({getattr(ctx.subject, 'name', '')}) — all features validated "
                "end-to-end in the browser and presented to the user."
            ),
        }


register_workflow(LivingUIWorkflow(), alias=LEGACY_WORKFLOW_ID)
