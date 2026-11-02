# General-purpose subagent

`general_agent` handles one self-contained objective: analysis, local file
work, a scoped code change, or command execution. Use `research_agent` for
source-cited fact gathering, `browser_agent` for interactive websites, and
the existing `walk_verify` flow for Agent App browser verification.

## Invocation and parallel work

Use the existing `spawn_subagent` action:

```json
{
  "agent_type": "general_agent",
  "query": "Read-only review of /workspace/project/backend for missing input validation. Do not modify files or run commands. Return findings with file paths, line numbers, and suggested fixes."
}
```

For parallel work, the parent emits multiple `spawn_subagent` calls in the
same decision batch. For example, one worker reviews `backend/` and another
reviews `frontend/`; the parent compares their results. Research and general
workers can be mixed in a batch. Keep batches small and use sequential
execution when a task depends on another result.

For edits, assign explicit ownership, such as: "Only modify
`/workspace/project/tests/test_parser.py`; implement these cases [...], run
the relevant tests from `/workspace/project`, and report changes and test
outcomes." Give each parallel writer different files or output paths. The
parent must also avoid modifying those files until the workers finish.

Every query must include the objective, absolute paths, necessary inputs,
project instructions, constraints, authorization, file ownership, expected
output and relevant checks. A worker starts without the parent's conversation,
memory, skills or task state. It cannot ask the user questions or spawn agents;
missing essential information is reported to the parent as a failure.

## Tools and results

The explicit tool allowlist reuses `list_folder`, `find_files`, `grep_files`,
`read_file`, `write_file`, `stream_edit`, `run_shell`, `web_search`, `web_fetch`,
`http_request` and `convert_to_markdown`. Windows also includes
`run_powershell`; Windows `run_shell` uses cmd.exe. The registry automatically
adds `sub_task_end`. No tool or skill loading is added to the runtime.

The worker ends with `sub_task_end`, returning its answer or changes, paths,
verification outcomes and limitations. `spawn_subagent` retains its existing
`status`, `result`, `child_task_id`, `iterations` and `agent_type` fields. The
parent checks status and reviews the result before using it. Failed or timed
out work can leave partial file changes; inspect those before retrying.

## Limits

- The definition sets 40 iterations and a 900-second wall-clock budget. The
  existing runner checks the wall-clock budget between steps; an in-flight
  tool call can exceed it. This is not a strict command timeout.
- Workers share the filesystem and existing permissions. Separate contexts
  and prompt instructions do not provide a filesystem or shell sandbox.
- Shell and HTTP access must stay within the parent's assigned authority;
  the allowlist alone does not prevent side effects through those tools.
- Scheduling, thread-pool capacity, Stop behavior, logging, caching and token
  attribution use the existing runtime without changes. There is no new
  cancellation guarantee, concurrency control, background agent service,
  persistence or rollback.

The delegation guidance ships in
`app/data/agent_file_system_template/AGENT.md` and the matching tracked
`agent_file_system/AGENT.md`. Existing installations with a
personalised `AGENT.md` should merge the updated Sub-Agents section into their
active instructions; adding this type does not overwrite personalised files.

## Maintenance and validation

The definition lives in `app/subagent/definitions/general_agent.py` and is
imported by `definitions/__init__.py`. The existing registry automatically
adds its name and description to `spawn_subagent`. Keep prompt, tools and
budgets in the definition rather than adding agent-specific runtime logic.

Run the offline checks with:

```text
python -m pytest tests/test_general_subagent.py tests/test_shell_actions.py
```

For a live smoke check, request two independent read-only reviews in one batch,
then a scoped change in a disposable directory. Confirm separate results,
correct file ownership and honest reporting of a blocked task. Live model
quality and Stop behavior are not established by the offline checks.
