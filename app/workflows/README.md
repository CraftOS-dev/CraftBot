# Workflows & the Agentic Loop

How a task turn flows through the shared loop, where deterministic
workflows plug in, and what changes when a task has no workflow at all.

## The layering

```
agent_core/core/registry/          the SEAMS (domain-blind plug points)
  task_workflows.py                  workflow_id string → workflow object
  extensions.py                      behavioral hooks (boot_restore, task_end_gate, …)

app/agentic/                       HOW agents run (one loop for everything)
  loop.py        AgentLoop          the turn skeleton (Template Method)
  engine.py      decide()           the decide phase: session-delta, LLM call, parse, retry
  steps.py                          the step CONTRACT: {kind: actions|llm|wait|end}
  parsing.py                        one decision-JSON parser for every loop
  task_driver.py TaskTurn           the task driver's policy (subclass of AgentLoop)

app/workflows/                     WHAT they do (deterministic programs)
  workflow.py    Workflow   the produce-and-verify engine (stage chain + WorkState)
  living_ui/workflow.py             LivingUIWorkflow(Workflow) — the one live domain
  living_ui/steps.py                BuildState, fix ledger, platform recorder entry points
  */subagents/                      the specialists (coding_agent, walk_verify, research_agent)

app/living_ui/                     the PRODUCT (manager, PB runtime, event taps)
```

`app/subagent/runner.py` (`SubAgentRunner`) is the second `AgentLoop`
subclass — the blocking loop that runs a spawned sub-agent from start to
`sub_task_end` inside one action. Same skeleton, different execution
policy (it executes actions itself; `TaskTurn` returns decisions for
`agent_base` to execute between limits/persistence/triggers).

## One task turn, hop by hop

1. A trigger fires → `agent_base._select_action_in_task` →
   `ActionRouter.select_action_in_task` constructs a `TaskTurn` and calls
   `run_turn(task)`.
2. `TaskTurn.__init__` resolves the task's workflow:
   `resolve_task_workflow(task)` maps the persisted `Task.workflow_id`
   back to the registered workflow object (or `None`).
3. `AgentLoop.run_turn` consults the step program:
   `TaskTurn.step_program` returns **`workflow.step`** — this single line
   is the whole coupling between the loop and `Workflow`.
4. `Workflow.step` → `compute`: load durable `WorkState` from disk,
   bundle it into a `StepContext`, and walk the stage chain — first stage
   with an opinion wins:

   `wait_for_user → answer_user → bootstrap → budget_gate → work_round → check → finish`

5. The returned step's `kind` routes the turn back in the loop:

   | kind      | What happens                                                                                                                                       | LLM call?    |
   | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
   | `actions` | `on_code_step` → `step_to_decisions` → validated payloads → `agent_base` executes                                                                  | no           |
   | `llm`     | the step's prompt rides the turn as a directive (`append_step_directive` — delivered even on delta turns), `allowed_actions` bounds the candidates | one, bounded |
   | `wait`    | no-op decision; task idles until the next trigger                                                                                                  | no           |
   | `end`     | becomes a `task_end` decision (still subject to the `task_end_gate` hook)                                                                          | no           |
   | `None`    | plain LLM turn — the model decides freely                                                                                                          | yes          |

6. **Outcomes come back through taps, not stages.** The stages never
   observe results; hooks record them into `WorkState`, and the _next_
   turn's `step()` reads the new state:

   | Event                         | Tap                                            | Records                                                  |
   | ----------------------------- | ---------------------------------------------- | -------------------------------------------------------- |
   | `spawn_subagent` completes    | `construction_events._record_specialist_spawn` | `record_spawn` / `record_walk_outcome` (verdict, fixlog) |
   | `living_ui_validate` finishes | `manager.launch_and_verify` wrapper            | `record_validate_outcome` (staged)                       |
   | user reply routed to the task | `registrations` `user_message_routed` hook     | `record_user_lead`                                       |

## The same skeleton, two behaviors

Every task — workflow or not — runs the identical turn skeleton. There is
exactly ONE fork point: what `step_program` returns.

```
trigger fires
  └─ agent_base → router.select_action_in_task → TaskTurn.run_turn(task)
       └─ step = consult( TaskTurn.step_program(task) )
                            │
          ┌─────────────────┴──────────────────┐
          │ workflow task                      │ plain task
          │ workflow.step → stage chain        │ step_program is None
          │ CODE decides this turn             │ LLM decides this turn
          └─────────────────┬──────────────────┘
                            ▼
          decisions returned → agent_base executes them   (identical again)
```

Everything else that differs is a _consequence_ of the task carrying a
`workflow_id`, decided once at task creation:

| Hop                  | Workflow task (Flow A)                                       | Plain task (Flow B)                              |
| -------------------- | ------------------------------------------------------------ | ------------------------------------------------ |
| Task creation        | `create_task(..., workflow_id="living_ui_creation")`         | `create_task(..., workflow_id=None)`             |
| System prompt        | `workflow.system_prompt` seeded into the session caches      | general agent prompt (identity/policies)         |
| Memory / skills      | opted out (`inject_memory` / `include_skills` flags)         | injected as usual                                |
| Per-turn context     | + `workflow.task_state()` directive block                    | generic task state                               |
| Who decides a turn   | code (stage chain); LLM only inside `"llm"` talk steps       | LLM, every turn                                  |
| Action execution     | `agent_base` executes the returned decisions                 | identical                                        |
| Memory between turns | durable `WorkState` on disk, written by taps                 | the event stream                                 |
| User msg mid-task    | `wait_for_user`/`answer_user` stages → ONE bounded LLM reply | LLM sees it in events, reacts freely             |
| Retry discipline     | round budget → budget-gate ask-user-and-wait, fix ledger     | none — LLM's judgment                            |
| Completion           | `"end"` step; `task_end_gate` refuses unvalidated completes  | LLM calls `task_end`; no gate listener claims it |

The two traces below are concrete runs of the left and right columns.

## Flow A — "Build me a habit tracker" (workflow-driven)

```
user msg → conversation mode select_action → LLM picks living_ui_scaffold
  → manager.create_project (template copy)
  → create_task(workflow_id="living_ui_creation") → trigger emitted

TURN 1   trigger → run_turn → workflow.step → stage_bootstrap
         → {"actions": spawn coding_agent(brief=requirements)}
         → agent_base executes; coding_agent runs its own AgentLoop
           (sub_task_end refused until build_passes + browser_verified pass)
         → TAP: record_spawn → fixlog

TURN 2   step: built, not staged → stage_work_round
         → {"actions": living_ui_validate} → launch pipeline
           (PB serve → schema import → typegen → build:debug → health)
         → TAP: record_validate_outcome → state.staged = True

TURN 3   step: staged, not verified → stage_check
         → {"actions": spawn walk_verify} → "VERDICT: FAIL — export dead"
         → TAP: record_walk_outcome → state.check_failures=[...]

TURN 4   step: failures present → stage_work_round (round 2)
         → {"actions": spawn coding_agent(failures + fixlog "already tried")}
         ⋯ user msg mid-build → stage_answer_user fires FIRST:
           {"kind":"llm", answer_user_prompt, allowed=[send_message]}
           → one bounded reply; TAP: record_user_lead

TURN N   walk passes → TAP: state.verified = True
         → on_verified stamps project.validation_passed_at

TURN N+1 stage_finish → {"actions": living_ui_notify_ready}
TURN N+2 stage_finish → {"kind":"llm", presentation_prompt}
         → present + task_end in one decision
         → task_end_gate hook: is_validated() true → complete
```

Budget exhausted instead? `stage_budget_gate` → one honest
`{"kind":"llm"}` report with `wait_for_user_reply=true` (including the
fix ledger's "already tried" block) → task parks; the reply is recorded
as a lead and the loop resumes.

## Flow B — "Summarize my invoice emails" (no workflow)

Same trigger loop and executors as Flow A — only the right-hand column of
the table above applies.

```
user msg → conversation mode → LLM picks task_start
  → create_task(mode="complex", workflow_id=None)   ← the fork, decided here
  → trigger emitted

TURN 1   run_turn → step_program is None → consult returns None
         → llm_turn: full candidates + task_state + events
         → LLM decides: search_gmail("invoice") → agent_base executes
         → result lands in the EVENT STREAM (no WorkState, no taps)

TURN 2   delta turn: only NEW events reach the cached session
         → LLM decides: get_message(...) ×3

TURN 3   LLM decides: send_message(summary) + task_end(complete)
         → task_end_gate: no listener claims this task → allowed
```

Same trigger loop, same `run_turn`, same executors — with no
`workflow_id` the step program is `None` every turn, the LLM makes every
decision from the event stream, and "memory" is the event stream itself
rather than `WorkState` + taps.

## Flow C — a second deterministic domain (hypothetical)

`living_ui_creation` is the only registered workflow today, but the
engine is domain-generic: any produce-and-verify job plugs in by
subclassing and answering a handful of questions. Example — a
"researched report" workflow (worker = the already-registered
`research_agent`; checker = a hypothetical `fact_check` sub-agent):

```python
class ReportWorkflow(Workflow):
    name = "report_writing"              # → Task.workflow_id
    worker_agent = "research_agent"       # who does a work round
    checker_agent = "fact_check"          # who independently verifies
    state_class = WorkState               # generic state is enough
    round_budget = 3

    def resolve_subject(self, task):      # which job does this task own?
        return report_dir_for(task)
    def state_dir(self, subject):         # where WorkState persists
        return subject
    def is_bootstrapped(self, ctx):       # has round 1 produced anything?
        return (ctx.state_dir / "draft.md").exists()
    def work_query(self, ctx):            # the worker's instruction —
        return f"Research and write draft.md on {ctx.subject.topic}. " \
               f"Address every gap: {ctx.state.check_failures}"
    def check_query(self, ctx):           # the checker's instruction
        return "Verify every claim in draft.md against sources. " \
               "End with VERDICT: PASS|FAIL and a per-claim list."

register_workflow(ReportWorkflow())
```

Plus one outcome tap (the domain's equivalent of
`_record_specialist_spawn`) routing `fact_check` results into
`record_check_outcome`. Then the identical machinery runs it:

```
user msg → task_start(workflow_id="report_writing") → trigger

TURN 1   step → stage_bootstrap: no draft.md yet
         → {"actions": spawn research_agent(work_query)}
         → agent executes, writes draft.md
         → TAP: record_work_outcome → state.staged = True

TURN 2   step: staged, not verified → stage_check
         → {"actions": spawn fact_check(check_query)}
         → "VERDICT: FAIL — claim 3 unsourced, stat in §2 outdated"
         → TAP: record_check_outcome → check_failures=[...]

TURN 3   step: failures present → stage_work_round (round 2)
         → {"actions": spawn research_agent(work_query now embeds
            the two failed claims)} → revised draft
         ⋯ user asks "how's it going?" → stage_answer_user:
           {"kind":"llm", answer_user_prompt} → one bounded reply

TURN N   fact_check passes → state.verified = True
TURN N+1 stage_finish → {"kind":"llm", presentation_prompt}
         → deliver the report + task_end in one decision
```

Nothing in `workflow.py` changes; the domain contributes only
subject resolution, the two queries, and its outcome tap. All the loop
guarantees (round budget → budget-gate ask, durable state across
restarts, independent verification, `task_end` gating) come for free.
