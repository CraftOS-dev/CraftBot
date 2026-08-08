# Write a custom action

An action is a Python function with an `@action` decorator. The decorator registers the function at import time and records the metadata the agent reads to decide when to call it. You write one file, add one decorator, and the agent gains a new capability. This page walks through the file layout, every metadata field, the execution modes, and how to test the result.

For the concepts behind actions and action sets, read [Actions and action sets](../core/concepts/actions-and-action-sets.md). For the full catalogue of built-in actions you can copy from, read [Actions reference](../core/concepts/default-actions.md).

## Where actions live

Actions live in `app/data/action/`, one file per action. On startup the loader walks that directory, imports every `.py` file whose name does not start with `__`, and the `@action` decorator in each file registers the action with the singleton registry. There is no manifest to edit and no central list to append to. Adding a file is the whole registration step.

Integration actions live one level deeper, under `app/data/action/integrations/<service>/`, and follow the same discovery rule. If you are adding a whole external service rather than a single action, read [Write a custom integration](custom-integration.md) instead.

Actions are not hot-reloaded. After you add or change a file, restart the agent so the loader re-imports it.

## The @action decorator

Import the decorator from `agent_core`:

```python
from agent_core import action
```

This is the only import that belongs at the top of an action file. Every other import your function needs goes inside the function body. The reason is explained in [Import rule for helpers](#import-rule-for-helpers) below.

The decorator takes keyword arguments only. `name` and `description` carry the most weight because they are what the selection model reads. The `description` teaches the model when to pick the action, so state what the action does, what input it expects, and what it returns.

## A minimal action

The following file is complete and runnable. Drop it at `app/data/action/count_words.py` and restart.

```python
# app/data/action/count_words.py
from agent_core import action


@action(
    name="count_words",
    description=(
        "Count the words in a block of text. "
        "Use when the user asks how long a passage is or wants a word count. "
        "Returns the integer word count."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=["text_tools"],
    input_schema={
        "text": {
            "type": "string",
            "example": "The quick brown fox.",
            "description": "The text to count words in.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "word_count": {
            "type": "integer",
            "example": 4,
            "description": "Number of whitespace-separated words in the text.",
        },
        "message": {
            "type": "string",
            "description": "Error message when status is 'error'.",
        },
    },
    test_payload={"text": "hello world", "simulated_mode": True},
)
def count_words(input_data: dict) -> dict:
    import re

    simulated_mode = input_data.get("simulated_mode", False)
    if simulated_mode:
        return {"status": "success", "word_count": 2, "message": ""}

    text = input_data.get("text", "")
    if not text:
        return {"status": "error", "word_count": 0, "message": "text is required."}

    words = re.findall(r"\S+", text)
    return {"status": "success", "word_count": len(words), "message": ""}
```

The function takes a single `input_data` dict and returns a dict. The keys in `input_data` are the keys you declared in `input_schema`. The returned dict flows back into the agent as the observation for the next turn, so it should match `output_schema`. Include a `status` field set to `"success"` or `"error"`, and put a human-readable reason in `message` on failure. Every built-in action follows this shape.

### How the schemas drive the model

`input_schema` and `output_schema` are the contract the selection model sees. Each field is a small object with three parts:

```python
"field_name": {
    "type": "string",            # string | integer | number | boolean | array | object
    "example": "example value",  # a realistic value the model copies as a hint
    "description": "What this field is for.",
}
```

The model reads the `type` to build a valid value, reads the `example` to see the expected format, and reads the `description` to understand the field. Realistic examples measurably improve how the model constructs arguments, so fill them in for every field. The output schema does the same job in reverse. It tells the model what keys to expect back so it can plan the following turn. Add `"required": True` to an input field when the action cannot run without it, as `web_search` does for its `query`.

## Metadata reference

Every keyword the `@action` decorator accepts, from `agent_core/core/action_framework/registry.py`:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | str | required | Unique snake_case identifier the model calls, for example `count_words`. Registering a second action with the same `name` overwrites the first. |
| `description` | str | `""` | What the model reads to decide when to pick the action. State what it does, what it expects, and what it returns. |
| `mode` | str | `"ALL"` | Which interface contexts surface the action. `"ALL"` makes it available everywhere. Leave it at `"ALL"` unless you have a reason to restrict visibility. |
| `execution_mode` | str | `"internal"` | `"internal"` runs the function in the agent process. `"sandboxed"` runs it in a separate persistent virtual environment. See below. |
| `platforms` | list[str] | `["all"]` | Operating systems this implementation supports: `"windows"`, `"linux"`, `"darwin"`, or `"all"`. Register the same `name` once per platform to provide OS-specific bodies. Lookup picks the current platform, then falls back to `"all"`. |
| `input_schema` | dict | `{}` | Parameter contract. One entry per input field, each with `type`, `example`, and `description`. |
| `output_schema` | dict | `{}` | Return contract. One entry per returned field, same shape as inputs. |
| `requirement` | list[str] | `[]` | Pip packages the action needs. Installed automatically before the action runs. |
| `test_payload` | dict | `None` | Sample input for a simulated dry run. Include `"simulated_mode": True` so the harness can exercise the action without real side effects. |
| `action_sets` | list[str] | `[]` | The sets this action belongs to. An action can be in several. Declaring a new set name creates that set. |
| `parallelizable` | bool | `True` | Whether the action may run alongside others in one turn. Set `False` for writes, state changes, and sends. |
| `irreversible` | bool | `False` | Whether the side effect cannot be undone once it reaches the outside world, such as sending a message or posting publicly. Guarded by the activity ledger. |
| `default` | bool | `False` | Legacy always-available flag. Prefer `action_sets`. When `True` the action is available without any set being selected. |

The decorator argument is `requirement` (singular). The registry stores it internally as `requirements`. There is no `timeout` argument on the decorator.

## Internal vs sandboxed execution

`execution_mode` decides where the function body runs.

`internal` runs the function inside the agent process. Use it for lightweight work and for actions that touch agent state through `app.internal_action_interface`, such as sending a message to the user or searching memory. Any packages listed in `requirement` are installed into the main environment.

`sandboxed` runs the function in a separate process backed by a persistent virtual environment at `~/.craftbot/sandbox_venv`. The environment is created on first use and reused after that. Packages listed in `requirement` install into that environment once and persist across calls. Use `sandboxed` for heavy dependencies you do not want in the main process, or for code you want isolated. A timeout kills a runaway sandboxed execution.

```python
@action(
    name="analyze_csv",
    description="Return a statistical summary of a CSV file.",
    execution_mode="sandboxed",
    requirement=["pandas"],
    action_sets=["document_processing"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "/data/report.csv",
            "description": "Path to the CSV file.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "row_count": {"type": "integer", "example": 1000},
    },
    test_payload={"file_path": "/tmp/test.csv", "simulated_mode": True},
)
def analyze_csv(input_data: dict) -> dict:
    import pandas as pd

    df = pd.read_csv(input_data["file_path"])
    return {"status": "success", "row_count": len(df)}
```

Either way the function returns a dict that becomes the observation for the next turn.

## Import rule for helpers

Every import your function uses must go inside the function body. Only the `from agent_core import action` line belongs at module top.

The registry extracts each action's source with the `inspect` module and runs the extracted body on its own. Names defined at module level, including top-level imports, are not in scope when the body runs. A helper referenced through a module-level import raises `NameError` at call time even though the file imported cleanly at startup. This is the single most common mistake when writing actions.

```python
# WRONG: module-top import; raises NameError at call time
from app.data.action.integrations._helpers import run_client

@action(name="do_thing", ...)
async def do_thing(input_data: dict) -> dict:
    return await run_client("service", "method")


# RIGHT: import inside the function body
@action(name="do_thing", ...)
async def do_thing(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("service", "method")
```

The same applies to the standard library. The minimal example above imports `re` inside `count_words` for this reason, and `analyze_csv` imports `pandas` inside its body. If your action raises `NameError` on a name that is clearly imported at the top of the file, this rule is why.

## Irreversible and parallel actions

Two flags govern how the runtime schedules and protects an action.

`parallelizable` defaults to `True`. The router may batch several parallelizable actions into one turn and run them concurrently. Set it to `False` on any action that writes, changes state, or sends something. A non-parallelizable action runs by itself, and the runtime drops the rest of the batch when one is selected. Every integration write action in this codebase sets `parallelizable=False`.

`irreversible` defaults to `False`. Set it to `True` when the side effect cannot be taken back once it leaves the process, such as sending an email or posting a public comment. Before an irreversible action runs, the activity ledger durably records the intent, and it records the outcome afterward. If the agent crashes between the send and the record, the ledger refuses a blind re-execution and surfaces a warning instead of sending twice. The `send_slack_message` action sets both `irreversible=True` and `parallelizable=False`, which is the correct pairing for any send.

## Making the action available

An action becomes usable through its `action_sets`. Sets are labels declared in the metadata, and the registry discovers them by scanning. Declaring `action_sets=["text_tools"]` creates the `text_tools` set with no other step. When a task starts, one selection call chooses the sets for that task based on its description, `core` is always included, and the union becomes the task's fixed vocabulary.

To make an action available to every task, add `"core"` to its sets, and use that sparingly because it costs tokens on every task. To scope it, put it in a descriptive set that a task selects only when it needs the capability. An action can join more than one set. The convention for high-value integration actions is to tag both a fine-grained set and an umbrella set, for example `action_sets=["slack_messages", "slack"]`.

Once the action is registered and its set is selected for a task, it appears in the router's candidate list and the agent can call it.

## Testing an action

Give every action a `test_payload` that includes `"simulated_mode": True`, and branch on that flag at the top of the function to return mock data without performing real work:

```python
simulated_mode = input_data.get("simulated_mode", False)
if simulated_mode:
    return {"status": "success", "word_count": 2, "message": ""}
```

The registry collects actions that have a `test_payload` and can run them in simulated mode, so honoring the flag lets the action be exercised safely. An action whose `test_payload` sets `"simulated_mode": False` is skipped by the simulated harness, which is the way to opt a real side effect out of automated runs.

You can also call the function directly in a Python session to confirm the return shape:

```python
from app.data.action.count_words import count_words

print(count_words({"text": "one two three"}))
# {'status': 'success', 'word_count': 3, 'message': ''}
```

Finally, restart the agent and ask it to do the thing your action does. The router should pick your action, and the action panel logs an `action_start` and `action_end` event for the call.

## Next

- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how the registry, sets, and router fit together
- [Actions reference](../core/concepts/default-actions.md): the full catalogue to copy patterns from
- [Write a custom integration](custom-integration.md): add a whole external service with its own action surface
