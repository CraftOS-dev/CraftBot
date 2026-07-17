---
name: living-ui-modify
description: Modify existing Living UI applications - add features, fix bugs, update UI, change backend logic. Identifies the project and hands the change to the platform build loop, which codes, verifies, and re-presents it.
action-sets:
  - file_operations
  - code_execution
  - living_ui
  - core
---

# Living UI Modifier

Change an existing Living UI app: add features, fix bugs, update UI
components, modify backend logic, or restructure data models.

**You do not edit the app's code yourself.** The PLATFORM modifies Living
UIs through its build loop — a coding agent makes the changes, the build
is verified, and an independent browser walk confirms every feature still
works before the app is re-presented. Your job is to point that loop at
the right project with a precise change request, then be the user's voice.

## Workflow

### 1. Identify the project

`livingui ls` (via run_shell) lists every project with id, name, status,
and type. Fuzzy-match the user's request against project names. If
ambiguous, list the candidates and ask the user which one.

### 2. Adopt it

```
living_ui_adopt(project_id, change_request)
```

- `change_request` must be SELF-CONTAINED: what to add/fix/change, where
  it lives in the app, and what "done" looks like — the coding agent sees
  only this text, not your conversation.
- Adoption makes this task the project's single owner (a previous owner
  task is superseded) and switches this task onto the platform build
  workflow. From the next turn on, the platform computes every step.

### 3. Let the platform drive

After adopting: send the user ONE short "update underway" message, then
follow the step directives that arrive each turn. Do NOT hand-edit app
files, re-run builds "to check", or spawn agents no directive named. The
loop codes → validates → browser-walks → re-presents automatically.

If the user writes mid-update, answer briefly; their message is recorded
and folded into the next round's work order.

## When NOT to adopt

Data or operations work that changes no code — inserting/updating rows,
running declared operations, exports, status checks — needs no build
loop. Use the livingui CLI directly (see the living-ui-manager skill):

```
livingui <project> select/insert/update/delete/sql ...
livingui <project> run <operation>
```

## Debugging context (evidence for the change_request)

When the user reports a bug, gather evidence BEFORE adopting so the
change_request is precise:

```
livingui <project_id> logs --tail 100    # backend + frontend console
livingui <project_id> status             # running? URLs? ports?
```

Log files (PocketBase-era projects): `<project>/logs/backend_output.log`
(backend), `<project>/pb_data/craftbot_console.jsonl` (frontend console).
Quote the exact error lines in your change_request — the coding agent
fixes root causes fastest when handed the real stack trace.
