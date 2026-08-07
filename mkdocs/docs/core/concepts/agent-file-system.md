# Agent file system

`agent_file_system/` at the project root is the agent's home directory: a dozen markdown files that hold its identity, its knowledge of you, and its memory of everything that's happened, plus a `workspace/` where task outputs land. Understanding who writes each file, and which ones you're meant to edit, is the single highest-leverage way to tune your agent.

## Overview
The files fall into three categories. Some are **yours to write**: the personality brief, your profile, the style guide. Some are **the agent's working notes**: the ops manual it consults and the task list it maintains. The rest are **records**: event logs, task history, and distilled memory, maintained by harness subsystems rather than by you or the agent.

The agent reads and writes these files with ordinary file actions, and a few (SOUL.md, AGENT.md pointers, USER.md) feed directly into every LLM call. Edit one and behavior changes on the next turn, with no restart.

The directory is seeded from templates in `app/data/agent_file_system_template/` on first run, and the `/reset` command restores the markdown files from those templates.

## The files

| File | Who writes it | May I edit it? | What it does |
|---|---|---|---|
| `SOUL.md` | You (agent only on your explicit request) | **Yes — the main personality knob** | Personality, tone, behavior. Injected into the system prompt every turn |
| `USER.md` | Onboarding wizard; agent, after confirming with you | **Yes** | Your profile: identity, timezone, communication preferences, life goals |
| `FORMAT.md` | You | **Yes** | Formatting standards the agent reads before generating any document |
| `GLOBAL_LIVING_UI.md` | You | **Yes** | Global design preferences for every [Living UI](../../living-ui/index.md) project — colors, theme, enforced rules |
| `AGENT.md` | Ships with CraftBot; agent appends learned operational fixes | Yes, carefully | The agent's versioned operations manual — runtime, errors, integrations, conventions. The agent greps it by `## <Topic>` |
| `PROACTIVE.md` | `recurring_*` actions and the planners | Prefer the actions; preserve the `<!-- PROACTIVE_TASKS_START/END -->` markers | Recurring proactive tasks plus the planner's Goals / Plan / Status — see [Proactive mode](../modes/proactive.md) |
| `MEMORY.md` | Memory processor only (nightly job) | **No** | Distilled long-term memory, one timestamped fact per line — see [Memory](memory.md) |
| `EVENT.md` | Event stream manager | **No** | Append-only chronological log of every event (actions, messages, errors) |
| `EVENT_UNPROCESSED.md` | Event stream manager | **No** | Staging buffer of events awaiting the nightly memory run; cleared after each run |
| `MISSION_INDEX_TEMPLATE.md` | Static template | **No** | Copied into `workspace/missions/<name>/INDEX.md` when a mission starts |

The "No" files are harness-managed. Hand-editing them creates inconsistencies the agent can't recover from: the memory pipeline expects `MEMORY.md` in its exact line format, and the event logs are the ground truth other subsystems replay. Read them freely, but never write to them.

## Files you should edit

Three files do most of the customization work:

**SOUL.md** shapes *how* the agent behaves. It's injected into the system prompt on every single turn, so edits take effect immediately and affect every interaction. Want it more terse, more playful, stricter about asking before acting? Say so here, or just tell the agent to update its soul, and it will ask for confirmation before saving.

**USER.md** shapes *who it's working for*. Onboarding fills the skeleton (identity, timezone, communication preferences, goals). Keep it current as things change. The agent reads it at the start of user-facing tasks and only writes durable, confirmed facts back. One-off requests don't land here.

**FORMAT.md** shapes *what it produces*. The agent consults it before generating any file. A `## global` section sets universal rules (colors, typography, writing style), and per-filetype sections (`## pptx`, `## docx`, `## xlsx`, `## pdf`) override it for that format. If every deck the agent makes has the wrong brand color, fix it once here and every future document follows.

`GLOBAL_LIVING_UI.md` plays the same role for generated apps: design preferences and enforced rules applied to every Living UI project, with per-project answers overriding when they conflict.

A useful side-effect to know: `AGENT.md`, `PROACTIVE.md`, `MEMORY.md`, `USER.md`, and `EVENT_UNPROCESSED.md` are indexed for the agent's semantic memory search, and a file watcher re-indexes them the moment they change, so edits to these files become retrievable knowledge, not just prompt text.

## workspace/

Everything the agent produces lands under `agent_file_system/workspace/`. Four zones with different lifecycles:

```text
workspace/
├── <files>                     Persistent outputs — reports, exports,
│                               anything you asked for. Never auto-cleaned.
├── sessions/<session_id>/      Per-session scratch: drafts, downloads,
│                               intermediate state. Created with the session;
│                               removed only when the session is deleted.
├── missions/<name>/            Multi-run initiatives. INDEX.md (from the
│                               template) records goal, findings, next steps —
│                               it's what a future run reads to restore context.
│                               Never auto-cleaned.
└── living_ui/<name>_<hash>/    Living UI projects — self-contained apps managed
                                by their own lifecycle actions. Don't rename or
                                delete these by hand.
```

The practical rules:

- **Deliverables go in the workspace root.** That's where "save it as frameworks.md" ends up, and where you go looking for outputs.
- **`sessions/` is scratch space.** If a run saved something there that you want to keep, ask for it to be moved to the workspace root.
- **Missions are for work bigger than one run** (a job hunt, a research program). The mission's `INDEX.md` is the durable state. Individual runs come and go.

## Configuration and limits

- **Location:** `agent_file_system/` in the project root. The template lives at `app/data/agent_file_system_template/`.
- **Edits apply on the next trigger**, with no restart. `SOUL.md` in particular takes effect on the very next turn.
- **Reset:** `/reset` deletes the markdown files and re-copies the templates. Workspace contents are handled separately, and Living UI projects are preserved by the generic reset (they have their own teardown).
- **Growth:** `EVENT.md` auto-rotates on size, and `EVENT_UNPROCESSED.md` is cleared by each successful memory run.
- **Not for secrets:** API keys and credentials live in `app/config/settings.json` and `.credentials/`, not in these markdown files.

## Next

- [Memory](memory.md): how events become `MEMORY.md` facts, and how the agent retrieves them
- [Proactive mode](../modes/proactive.md): the system that reads and maintains `PROACTIVE.md`
- [Living UI](../../living-ui/index.md): the projects living under `workspace/living_ui/`
