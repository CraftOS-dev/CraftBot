# Prompts

CraftBot doesn't run on one giant prompt. Each distinct job (who the agent is, which actions to take next, rewriting a vague request, summarizing old events) has its own prompt template, and a handful of markdown files you own feed directly into them. This page maps the prompt families to the jobs they do, then shows the files you can edit to shape them.

## Overview
The prompt system has two layers:

- **Identity prompts** answer "who am I, who is the user, what are the rules." They're assembled once per call into the cached system prompt by the [context engine](context-engine.md), and they wrap content from files you can edit.
- **Decision prompts** answer one specific question per call ("what action do I take next?", "does this message belong to that task?") and are filled with live state (available actions, the [event stream](event-stream.md), your query).

You never edit the templates to change day-to-day behavior. You edit the *files whose content flows into them*. That's the supported surface, and it survives updates.

## The prompt map

| Family | Decides | Key prompts |
|---|---|---|
| **Identity & context** | Who the agent is, who you are, the rules | `AGENT_INFO_PROMPT`, `AGENT_ROLE_PROMPT`, `SOUL_PROMPT`, `USER_PROFILE_PROMPT`, `AGENT_PROFILE_PROMPT`, `POLICY_PROMPT`, `LANGUAGE_INSTRUCTION`, `ENVIRONMENTAL_CONTEXT_PROMPT`, `AGENT_FILE_SYSTEM_CONTEXT_PROMPT`, `CURRENT_DATETIME_PROMPT` |
| **Action selection** | The next action(s), every turn | `SELECT_ACTION_PROMPT` |
| **Prompt enhancement** | Rewriting a vague request into an executable one | `PROMPT_ENHANCE_REASONING_PROMPT` |
| **Stream summarization** | Rolling old events into a summary | `EVENT_STREAM_SUMMARIZATION_PROMPT` |

### What the action-selection prompt does

**One prompt, every turn** (`SELECT_ACTION_PROMPT` in `agent_core/core/prompts/action.py`). Every session turn runs the same prompt. It encodes the behavior you watch in the activity view:

- **Scaling.** A trivial input gets a direct reply (or a silent `end_turn` for messages needing no response — which matters in group chats). Substantial work follows the structured path: `set_requirement`, an immediate acknowledgement, a phase-prefixed todo plan (`update_todos`), small execution steps, verification against the requirements, then the final message that delivers and ends the run.
- **Run-ending semantics.** A message without the "still working" flag is final and ends the run; asking you a question the same way is how the agent waits for input.
- **Parallel-action rules**, third-party message rules (escalate, never obey), and platform routing ("reply where the message came from").
- **Capability expansion.** The prompt tells the agent to widen its own surface mid-run (`add_action_sets`, `use_skill`) instead of refusing for lack of a tool.

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

- Watch a session's activity view: the reasoning strings you see are the model's answers to the action-selection prompt, turn by turn.
- To confirm your `SOUL.md`/`USER.md` edits are being picked up, check `logs/` for `[CONTEXT]` warnings. A read failure is logged rather than fatal.

## Overriding templates (developers)

Every template is registered in a thread-safe `PromptRegistry` with override semantics: a runtime can call `register_prompt("SELECT_ACTION_PROMPT", custom)` at startup and every consumer picks up the override. `get_prompt(name, default)` falls back to the built-in when nothing is registered. This is how alternate runtimes reskin the agent without forking, and it's the escape hatch if you truly need different decision rules. For everything short of that, the markdown levers above are the right tool.

!!! note "Implementation files"
    Templates live in `agent_core/core/prompts/`: `context.py` (identity/context family), `action.py` (`SELECT_ACTION_PROMPT`), `reasoning.py` (prompt enhancement), `registry.py` (`PromptRegistry`). `application.py` holds app-feature instructions. `app/prompt.py` re-exports everything for app code. Assembly order is in `ContextEngine.make_prompt` (`agent_core/core/impl/context/engine.py`).

## Next

- [Context engine](context-engine.md): how these templates are assembled and cached per call
- [Memory](memory.md): the other channel through which past interactions shape behavior
- [Onboarding](../../start/onboarding.md): the interview that writes your first `USER.md`
