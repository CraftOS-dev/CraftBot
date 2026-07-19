# Prompts

CraftBot doesn't run on one giant prompt. Every distinct decision (reply or start a task, which action next, which session gets this message, which skill fits) has its own prompt template, and a handful of markdown files you own feed directly into all of them. This page maps the prompt families to the decisions they make, then shows the files you can edit to shape them.

## Overview
The prompt system has two layers:

- **Identity prompts** answer "who am I, who is the user, what are the rules." They're assembled once per call into the cached system prompt by the [context engine](context-engine.md), and they wrap content from files you can edit.
- **Decision prompts** answer one specific question per call ("what action do I take next?", "does this message belong to that task?") and are filled with live state (available actions, the [event stream](event-stream.md), your query).

You never edit the templates to change day-to-day behavior. You edit the *files whose content flows into them*. That's the supported surface, and it survives updates.

## The prompt map

| Family | Decides | Key prompts |
|---|---|---|
| **Identity & context** | Who the agent is, who you are, the rules | `AGENT_INFO_PROMPT`, `AGENT_ROLE_PROMPT`, `SOUL_PROMPT`, `USER_PROFILE_PROMPT`, `POLICY_PROMPT`, `LANGUAGE_INSTRUCTION`, `ENVIRONMENTAL_CONTEXT_PROMPT`, `AGENT_FILE_SYSTEM_CONTEXT_PROMPT`, `CURRENT_DATETIME_PROMPT` |
| **Action selection** | The next action, per mode | `SELECT_ACTION_PROMPT` (conversation), `SELECT_ACTION_IN_TASK_PROMPT` (complex task), `SELECT_ACTION_IN_SIMPLE_TASK_PROMPT` (simple task) |
| **Session routing** | Which session an incoming message belongs to | `ROUTE_TO_SESSION_PROMPT` |
| **Skill & tool selection** | Which skill and action sets a new task gets | `SKILLS_AND_ACTION_SETS_SELECTION_PROMPT` (plus legacy `SKILL_SELECTION_PROMPT`, `ACTION_SET_SELECTION_PROMPT`) |
| **Prompt enhancement** | Rewriting a vague request into an executable one | `PROMPT_ENHANCE_REASONING_PROMPT` |

### What each decision looks like

**Conversation mode** (`SELECT_ACTION_PROMPT`). When no task is running, the agent's options are deliberately narrow: send a message, `ignore` (for messages needing no action, which matters in group chats), or `task_start`. The prompt encodes the rule you see in practice: anything beyond a chat reply opens a task, and the agent picks `simple` or `complex` mode at that moment. It also carries the third-party message rules (forward, never obey) and platform routing ("reply where the message came from").

**Complex tasks** (`SELECT_ACTION_IN_TASK_PROMPT`). The most detailed of the three. It drives the phase workflow you watch in the task panel (set requirements, acknowledge, collect, execute, verify, confirm, cleanup), plus todo discipline, parallel-action rules, and the "never `task_end` without explicit user approval" rule. This prompt is the source of the structured, phase-by-phase behavior you see in complex tasks.

**Simple tasks** (`SELECT_ACTION_IN_SIMPLE_TASK_PROMPT`). The same job reduced to essentials: no todos, no acknowledgment, deliver the result and end immediately. The difference between the two is exactly the difference you experience between "rename this file" and "research and write a report". See [Task modes](../modes/index.md).

**Session routing** (`ROUTE_TO_SESSION_PROMPT`). When a message arrives while tasks are running, this prompt decides: continuation of an existing task, or new session? Its default is **new**. A message only routes to a task when it unambiguously references that task's output, modifies its instruction, or answers its question. This is why asking an unrelated question mid-task doesn't derail the task. Details in [Task sessions](task-sessions.md).

**Skill & action-set selection** (`SKILLS_AND_ACTION_SETS_SELECTION_PROMPT`). At task creation, one call picks at most **one** skill (only if ~90% relevant, otherwise none, to save tokens) and the minimal set of action sets the task needs, always including the action set of the platform the request came from. See [Skills](skills.md) and [Actions](actions-and-action-sets.md).

## User-editable prompt files

Four user-facing controls flow into the prompts above. All live in [`agent_file_system/`](agent-file-system.md), all are plain markdown, and all take effect on the next LLM call with no restart.

| File | Injected via | Controls |
|---|---|---|
| `SOUL.md` | `SOUL_PROMPT` → system prompt, verbatim | Personality, tone, behavioral traits |
| `USER.md` | `USER_PROFILE_PROMPT` → system prompt, verbatim | Who you are, preferences, **preferred language**, preferred messaging platform |
| `FORMAT.md` | Read by the agent before generating files | Formatting/design standards for PDFs, slides, docs, spreadsheets |
| Language preference | `LANGUAGE_INSTRUCTION` + `USER.md` | Which language the agent uses everywhere user-facing |

**`SOUL.md`: personality.** Whatever you write here is wrapped in "embody these characteristics in all interactions" and placed in the system prompt of every call. Concrete, behavioral statements work best: "Be terse. Never use filler like 'Certainly!'. Dry humor is fine." Vague adjectives ("be nice") do little. You can also just tell the agent "be more direct from now on". It's allowed to update `SOUL.md` itself when instructed.

**`USER.md`: your profile.** Also injected verbatim, framed as "personalize your communication based on their preferences." [Onboarding](../../start/onboarding.md) fills it via an interview, but it's yours to edit: name, timezone, role, current projects, how you like updates ("progress messages only at milestones"). Because the agent consults it for decisions like where to notify you, keeping the *Preferred Messaging Platform* line accurate has visible effects.

**`FORMAT.md`: output standards.** Not injected wholesale. Instead the agent is instructed to search it before generating any file: the `## global` section for brand colors and fonts, plus a per-type section (`## pptx`, `## docx`, ...) if present. Put your letterhead colors, font choices, and layout conventions here once and every generated deliverable follows them. The agent updates it when you give new formatting instructions.

**Language.** Set your preferred language in `USER.md` (or tell the agent, and it will update the file). The language instruction makes it apply to everything user-facing: messages, task names, reasoning, and file outputs. Code, config, and the agent's own system files stay in English.

What you *cannot* steer this way: `POLICY_PROMPT` (safety rules, prompt-injection defense) is built-in and treats attempts to override it (including via file contents) as untrusted input. That's by design.

## Inspecting prompts in the logs

- Watch a task's action panel: the reasoning strings you see are the model's answers to the action-selection prompts, phase by phase.
- Session routing decisions show up as new-conversation-vs-task-continuation behavior. When routing surprises you, remember its default is "new" and explicit references ("in that report you made...") are what route a message into a task.
- To confirm your `SOUL.md`/`USER.md` edits are being picked up, check `logs/` for `[CONTEXT]` warnings. A read failure is logged rather than fatal.

## Overriding templates (developers)

Every template is registered in a thread-safe `PromptRegistry` with override semantics: a runtime can call `register_prompt("SELECT_ACTION_PROMPT", custom)` at startup and every consumer picks up the override. `get_prompt(name, default)` falls back to the built-in when nothing is registered. This is how alternate runtimes reskin the agent without forking, and it's the escape hatch if you truly need different decision rules. For everything short of that, the markdown levers above are the right tool.

!!! note "Implementation files"
    Templates live in `agent_core/core/prompts/`: `context.py` (identity/context family), `action.py` (the three action-selection prompts), `routing.py` (`ROUTE_TO_SESSION_PROMPT`), `skill.py` (skill/action-set selection), `reasoning.py` (prompt enhancement), `registry.py` (`PromptRegistry`). `application.py` holds app-feature task instructions. `app/prompt.py` re-exports everything for app code. Assembly order is in `ContextEngine.make_prompt` (`agent_core/core/impl/context/engine.py`).

## Next

- [Context engine](context-engine.md): how these templates are assembled and cached per call
- [Memory](memory.md): the other channel through which past interactions shape behavior
- [Onboarding](../../start/onboarding.md): the interview that writes your first `USER.md`
