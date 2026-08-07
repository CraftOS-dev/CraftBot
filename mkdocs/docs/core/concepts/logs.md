# Logs

When the agent does something unexpected (a task stalls, a schedule doesn't fire, an action errors) the logs are the ground truth. Every run writes a timestamped folder under `logs/` at the project root, capturing what every subsystem did, down to module and line number.

## Overview
CraftBot logs with **Loguru**, and each process run gets **one folder**: `logs/<timestamp>/` (e.g. `logs/20260717085754/`). Inside, the same stream is split by *session* and by *who was speaking*:

| File | Contains | Read it when |
|---|---|---|
| `all.log` | Everything, interleaved in true time order — every session, main agent and every sub-agent | You're debugging anything that crosses sessions or agents, or just want the full picture. **Start here** |
| `<session_id>/session.log` | One folder per session; that session's own lines. The main session's folder is `main/` | You want one lane's story without the noise of the others |
| `<session_id>/<agent_tag>.log` | One file per sub-agent, inside the session that spawned it | A specific delegated job misbehaved — see [Sub-agents](sub-agents.md) |

The split works through attribution tags: every line carries a `session` field and an `agent` field (`main` for the main agent, `sub:<type>:<id>` for lines emitted inside a sub-agent's run, including its actions and LLM calls). The per-session and per-sub-agent files are filtered views of the same stream. `all.log` keeps the cross-session ordering that the filtered files lose.

## Reading a line

```
2026-07-17 02:17:32.811 | INFO     | main           | main                   | app.scheduler.manager:initialize:83 - [SCHEDULER] Initialized with 5 schedule(s)
^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^   ^^^^^^^^^^^^^   ^^^^                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
timestamp                 level      session         agent                    module:function:line                  message
```

- **Level:** `DEBUG` < `INFO` < `WARNING` < `ERROR`. The file threshold is INFO, and the harness narrates generously at INFO, so most context is captured by default.
- **Session / agent:** which lane and which worker emitted the line.
- **module:function:line** points at the exact source location. Open the module and jump to the line for full context.
- Errors include full tracebacks (`backtrace` and `diagnose` are enabled).

Note that the loguru sinks are file-only. The console is not a log sink, so tail the files rather than watching the terminal.

## Subsystem tags

Most subsystems prefix their messages with a bracketed tag, which makes grep the natural interface:

| Tag | Covers |
|---|---|
| `[REACT]` | The agent loop — each trigger consumed, each reaction; `[REACT ERROR]` for caught loop-level exceptions |
| `[ACTION]` | Action preparation and execution |
| `[SESSION]` | Session lifecycle and caches |
| `[MEMORY]` | Memory indexing, processing, retrieval. See [Memory](memory.md) |
| `[MCP]` | MCP server init, connection, tool calls |
| `[SCHEDULER]` | Schedule loops: sleep-until times, wakes, fires. See [Scheduling](scheduling.md) |
| `[PROACTIVE]` | Proactive heartbeat and planners. See [Proactive mode](../modes/proactive.md) |
| `[LIMIT]` | Action/token budget warnings and the continue/abort gate |

## Grep recipes

Find the newest run first, since it's the one you almost always want:

```bash
cd logs && ls -t | head -2        # newest run folders
```

**Why did a run fail?** Errors first, then rewind for the story leading up to them:

```bash
grep -n "ERROR" logs/<run>/all.log | tail -20
grep -n "\[REACT ERROR\]" logs/<run>/all.log
```

Then open `all.log` at the line numbers you found and read upward. The `[ACTION]` and `[REACT]` lines just before an error usually name the exact action and input that broke.

**Follow one action end to end.** Every action is logged by name at preparation and execution:

```bash
grep -n "web_fetch" logs/<run>/all.log          # one action's full trail
grep -n "\[ACTION\]" logs/<run>/all.log | tail  # recent action activity
```

**Watch the scheduler live.** This shows whether a schedule fired and when it fires next:

```bash
tail -f logs/<run>/all.log | grep "\[SCHEDULER\]"
```

You'll see each loop's `sleeping until <time>` line and `Fired schedule: <id>` on every fire. This is the fastest way to confirm a schedule is armed and firing.

**A sub-agent went wrong.** Read its dedicated file (`logs/<run>/<session_id>/<agent_tag>.log`, inside the session that spawned it) for the clean story, then find the same timestamps in `all.log` to see what the main agent was doing around it.

## Other log surfaces

Two complementary surfaces cover what the run logs don't:

- **`agent_file_system/EVENT.md`** is the *agent's* perspective: the events it produced and observed (actions started/ended, messages, errors), rather than harness internals. It is good for "what did the agent think happened", while the run logs are "what actually happened". See [Agent file system](agent-file-system.md).
- **`diagnostic/logs/actions/`** holds per-action JSON dumps (`<timestamp>_<action>.log.json`) with the full input and output of individual actions, written when actions are exercised through the diagnostic harness (`diagnostic/action_diagnose.py`). Use it to replay exactly what one action received and returned.

When CraftBot runs as a background service, the service manager keeps its own separate `craftbot.log` for startup/lifecycle issues ("why didn't it start" rather than "why did it misbehave"). This is covered in [Service mode](../../start/service-mode.md).

## Configuration and limits

- **Location:** `logs/` in the project root, one folder per process start. Restarting CraftBot begins a fresh folder. If a problem happened "yesterday", it's in an older folder, not the current one.
- **Rotation:** `all.log` and the per-session `session.log` files rotate at **50 MB** and are retained for **14 days**. Both are set in `app/logger.py`, which is also where you'd change the format or thresholds.
- **Sub-agent files** exist only for runs that actually spawned sub-agents, and each sink is attached when the sub-agent starts and detached when it ends.
- **Size:** the INFO threshold is verbose by design. A busy day of tasks produces logs in the hundreds of KB to MB range. Retention keeps this bounded.

## Next

- [Agent file system](agent-file-system.md): `EVENT.md` and the other on-disk records the agent keeps
- [Scheduling](scheduling.md): what the `[SCHEDULER]` lines you just grepped actually do
- [Service mode](../../start/service-mode.md): the service's own `craftbot.log` and where it lives
