# Event types

An event is one entry in a [session](../core/concepts/task-sessions.md)'s event stream: a message, a typed category, a severity, and optional structured fields. The [event stream](../core/concepts/event-stream.md) concept page explains the stream mechanics (one stream per session, the verbatim tail plus rolling summary, how snapshots reach the model). This page is the per-type catalogue: what each `EventType` value means, what fields an event record carries, and how consumers route on them.

The type is a closed set. It is defined as the `EventType` enum in `agent_core/core/event_stream/event.py` and has exactly 12 values. Consumers route on this field and never on message text.

## Event types

The "UI render" column describes what the browser event transformer (`app/ui_layer/events/transformer.py`) produces for each type. Several types are deliberately stream-only: they are context for the model, not for you.

| `EventType` | Emitted when | UI render |
|---|---|---|
| `user_message` | A message arrives from you, entered locally or routed from a connected platform. | Shown as a chat bubble, emitted directly by the controller. The transformer suppresses the stream echo to avoid a double render. |
| `agent_message` | The agent sends a chat reply (the `send_message` action). | Chat bubble. The event's `continue_work` flag tells the UI whether this is a mid-run progress update (keep the "Working…" indicator up) or a final, run-ending reply. |
| `system` | The harness posts a notice: a status change, a warning, or a loop-detection notice upgraded to `system`. | System notice line. |
| `error` | The agent surfaces a failure worth showing. | Error notice line. |
| `reasoning` | The LLM emits its rationale for the next action(s). | Reasoning block, keyed so repeated updates group together. |
| `action_start` | Immediately before an action runs. | Action row opens. Suppressed when `action_name` is the internal control action `end_turn`. |
| `action_end` | After an action finishes. | Action row closes; status is read from `action_output["status"]`, not from message text. Suppressed for the same internal action name. |
| `trigger` | A non-user trigger's instruction is written into the stream when its turn claims it (user messages enter as `user_message` instead). | Hidden. The chat-side announcement is emitted separately by the runtime, so the stream copy never double-posts. |
| `waiting_for_user` | The agent parks a question for you in the stream. | Hidden by the transformer; the question itself reaches you as an `agent_message`. |
| `relevant_memories` | Memory retrieval injects recall pointers into the stream. | Hidden. It is context for the model, not for you. |
| `todos` | The run's todo list changes. | Hidden by the transformer; the checklist renders from session state on a separate path. |
| `internal` | Bookkeeping the agent records for itself, including the Continue/Stop limit-choice notice. | Hidden. |

Every type above is documented; the enum contains no others. Producers must pass `event_type` explicitly at `log()` time. An event that reaches the transformer with no `event_type` renders as nothing, which flags an unmigrated producer.

Alongside the closed-set type, each event also carries a free-text `kind` label that appears in `EVENT.md` lines. One `kind` worth knowing: `action_error` marks an action that was **dropped before execution** for violating a parallel-execution constraint (for example, two `send_message` calls in one batch). An action that ran and failed is a normal `action_end` whose output carries `status: "error"`.

## Event record fields

Each event is an `Event` dataclass. The stream wraps it in an `EventRecord` that adds timing and a repeat counter. Fields, from the source:

| Field | Meaning |
|---|---|
| `message` | The full event payload used for prompts and debugging. Oversized messages are externalized to a temp file and replaced by a pointer, so a single huge payload cannot bloat every later turn. |
| `kind` | A human-readable label for the prompt-facing snapshot (for example `agent message to platform: Telegram`). Free text. Not used for routing. |
| `severity` | One of `DEBUG`, `INFO`, `WARN`, `ERROR`. Unknown values fall back to `INFO`. |
| `display_message` | An optional shorter or friendlier string for the UI. The full `message` stays intact for the model and for logs. |
| `ts` | Creation timestamp, stored in UTC and rendered in local time in compact lines. |
| `event_type` | The closed-set category from the table above. The one field consumers route on. |
| `action_name` | Canonical action identifier, set on `action_start` and `action_end`. `None` otherwise. |
| `action_display_name` | User-facing action name. Consumers fall back to a title-cased `action_name` when it is absent. |
| `action_id` | Stable identifier shared by an action's start and end events so they correlate without parsing. |
| `action_input` | Structured input payload on `action_start`. |
| `action_output` | Structured output payload on `action_end`, including the `status` key the UI reads. |
| `platform` | Originating or destination platform for chat messages (for example `Telegram`, `CraftBot Interface`). |
| `continue_work` | On `agent_message` only: `true` when the agent sent this as a mid-run progress update and will keep working; `None`/`false` for final replies and non-chat events. |
| `repeat_count` | On the wrapping `EventRecord`: how many identical consecutive occurrences collapsed into this record. Defaults to 1. |

## Action event pairing

An `action_start` and its `action_end` share the same `action_id`. That id is generated by the action manager (as `run_id`) and set on both events, so a consumer can match a start to its end even when several copies of the same action run at once and finish within the same second. Without the shared id, two parallel `web_search` calls would be indistinguishable by name and timestamp alone.

Two details follow from routing on structured fields rather than text:

- **Status comes from the payload.** `action_end` classification reads `action_output["status"] == "error"`. The message string is never inspected, so an action whose output text happens to contain the word "error" is not miscoloured.
- **Internal actions stay hidden.** `action_start` and `action_end` whose `action_name` is `end_turn` produce no UI row. It is control flow (the action that ends a run silently), not user-visible work.

Repeated identical events do not each get their own record. When the same event recurs, the stream increments `repeat_count` on the existing `EventRecord` instead of appending a new one. The compact line renders the count as an ` xN` suffix, so a stall that logs the same notice fifty times reads as one line with ` x50` rather than fifty lines.

## Event routing and legacy upgrade

The routing contract is a single dispatch on `event_type`. The transformer holds a table mapping each `EventType` to one builder and consults nothing else. It must not read `kind` or `message` substrings to decide which UI event to make, whether to hide an event, or how to classify a status. This rule exists because the older substring approach hid a legitimate chat message that contained the word "Ignored" (it matched `"ignore" in message_lower`). Adding a new UI variant means adding an `EventType` value and a dispatch entry, never a new string check at a call site.

Persisted events written before `event_type` existed have no value for that field. They are upgraded once at load time in `Event.from_dict()`, which maps the old free-text `kind` to a type through `_legacy_event_type_from_kind`. A sample of that map:

| Legacy `kind` | Upgraded `event_type` |
|---|---|
| `action_error` | `action_end` |
| `gui action start` / `gui action end` | `action_start` / `action_end` |
| `agent reasoning` | `reasoning` |
| `warning`, `loop_detection_warning` | `system` |
| `agent message ...` (prefix) | `agent_message` |
| `user message ...` (prefix) | `user_message` |

This path is for restored data only. New code sets `event_type` at `log()` time and never calls the legacy mapper. Once all persisted data has rolled over, the map and its helper can be removed.

## Events and the memory buffer

Every event is also appended to `EVENT.md`, the complete on-disk history. A subset is additionally staged in `EVENT_UNPROCESSED.md`, the buffer the [memory pipeline](../core/concepts/memory.md) distills. Routine event kinds the memory processor would always discard are filtered out at write time by `SKIP_UNPROCESSED_EVENT_TYPES` (in `agent_core/core/impl/event_stream/manager.py`), so the buffer holds only dialogue and meaningful state changes.

The filtered kinds are `action_start`, `action_end`, the GUI action kinds, `agent reasoning`, `screen_description`, `todos`, `error`, `waiting_for_user`, and `relevant_memories`. Separately, memory-processing runs flip a skip flag (`set_skip_unprocessed_logging`) for their duration, so the distillation run's own events never write to the buffer and cannot loop back into the next run.

## Next

- [Event stream](../core/concepts/event-stream.md): the concept, the tail-plus-summary mechanics, and on-disk files.
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): the actions that produce `action_start` and `action_end`.
- [Memory](../core/concepts/memory.md): how buffered events become long-term recall.
- [Agent MD files](agent-md-files.md): the schema of `EVENT.md` and the other files under `agent_file_system/`.
