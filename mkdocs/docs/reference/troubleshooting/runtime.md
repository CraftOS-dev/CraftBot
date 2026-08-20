# Runtime issues

This page covers CraftBot starting up, running, and behaving as expected once installed. Each area lists symptoms with their cause and fix. For install-time failures such as a failed dependency install, start with the [Install troubleshooting table](../../start/install.md#troubleshooting). For anything you cannot resolve here, read `logs/<run>/all.log`. See [Logs](../../core/concepts/logs.md).

## Startup and launch

The backend runs on port `7926` and the browser interface on port `7925`. Launch problems are usually a busy port, a missing runtime, or an unfinished build.

| Symptom | Cause | Fix |
|---|---|---|
| `Port 7925` or `7926` already in use on launch | Another process, or an earlier CraftBot that did not exit, owns the port | Run `python craftbot.py stop`, then start again. Or launch on other ports with `python run.py --frontend-port PORT --backend-port PORT` |
| `npm not found in PATH` | Node.js is missing, and browser mode requires it | Install the Node.js LTS from [nodejs.org](https://nodejs.org/), restart the terminal, and run again. Or use `python run.py --cli`, which needs no Node.js |
| Browser opens but the page stays blank | The frontend is still building on first launch, or the build failed | Wait for the first build to finish. If it does not load, check `python craftbot.py logs` for the build error and re-run `python install.py` |
| The interface loads but never connects | The backend on port `7926` is not up | Confirm with `python craftbot.py status`. In the browser network tab, a failed WebSocket means the backend did not start. Read `logs/<run>/main.log` for the startup error |
| The agent hangs on startup and never reports ready | A provider connection test is blocking, or a required setting is missing | Read `logs/<run>/main.log` for the last line before the stall. A bad API key or an unreachable Ollama URL is the usual cause. See [Provider issues](providers.md) |

## Service does not auto-start

The automatic install registers CraftBot to start when you log in. If it does not, the registration or the service log tells you why.

| Symptom | Cause | Fix |
|---|---|---|
| CraftBot is not running after you log in | Auto-start is not registered, or the registered task failed | Run `python craftbot.py status` to confirm registration. Re-register by running `python craftbot.py install` again |
| The service starts, then exits | A startup error crashes the background process | Read the service log `craftbot.log`, which is separate from the run logs and covers lifecycle issues. See [Service mode](../../start/service-mode.md) for its location per platform |
| Auto-start works on one machine but not another | Platform-specific registration differs across Windows, macOS, and Linux | See the platform deep-dive in [Service mode](../../start/service-mode.md#platform-deep-dive) |

## The agent does not respond or hangs

When you send a message and nothing comes back, the cause is almost always the backend, the provider, or a task busy on a long action.

| Symptom | Cause | Fix |
|---|---|---|
| No reply at all to a chat message | The backend is down | Run `python craftbot.py status`. Start it if it is not running |
| The agent accepts messages but never answers | No model provider is configured | Complete onboarding, or set a key with the `/provider` command. See [Provider issues](providers.md) |
| The agent seems to hang partway through a task | It is running a long action, such as a web fetch or a large file operation | Check the action panel for the running action, and `logs/<run>/all.log` for the matching `[ACTION]` line. A single slow action is normal, not a hang |
| The reply stops mid-thought and never resumes | The provider errored repeatedly and the agent backed off | Search the log for repeated provider errors. See [Provider issues](providers.md) |

## Tasks

A complex task runs many actions in a loop. Two guardrails can pause or hold a task, and both are working as designed.

| Symptom | Cause | Fix |
|---|---|---|
| A task pauses and asks whether to continue or abort | The task hit its action budget of `500` actions or its token budget of `12,000,000` tokens. The log records `Action limit reached` or `Token limit reached` under the `[LIMIT]` tag, and the task status becomes `paused` | Choose **Continue** to reset the counters and resume, or **Abort** to end the task. The paused task stays alive for 3 hours waiting for your choice |
| A task ends much sooner than expected | It reached one of the limits above and you chose to abort, or the agent decided the work was done | Read the `[TASK]` lines in the log to see how it ended. Break large work into smaller tasks so each stays within budget |
| A task will not end and keeps asking for approval | An action needs your confirmation before it runs | Answer the prompt in chat. Irreversible actions request approval by design. See [Complex tasks](../../core/modes/complex-task.md) |

## Memory

Memory captures facts to `MEMORY.md` and indexes them for recall. If the agent does not remember something, check that memory is enabled and that the processor has run.

| Symptom | Cause | Fix |
|---|---|---|
| The agent does not recall something you told it today | The fact is captured but not yet distilled, or memory is off | Confirm `memory.enabled` is `true` in `settings.json`. Recent facts are searchable before the nightly run, so also check the query cleared the relevance floor in the `[MEMORY QUERY]` and `[MEMORY RESULT]` log lines |
| Memory never seems to update | The nightly processor did not run | The processor runs once a day at 3 a.m., and a startup check replays it when CraftBot launches with unprocessed events. Restart to trigger the replay, then check the log for the memory-processing task |
| An edit to an indexed file is not reflected in recall | The file watcher has not re-indexed yet | Re-indexing runs after a short debounce. Wait, then retry. A restart forces a full re-scan |

See [Memory](../../core/concepts/memory.md) for the full pipeline and the `MEMORY.md` format.

## Scheduling

Schedules fire only while CraftBot is running. The scheduler logs every sleep and every fire under the `[SCHEDULER]` tag.

| Symptom | Cause | Fix |
|---|---|---|
| A schedule did not fire | CraftBot was not running at the scheduled time | Schedules need the process alive. Keep CraftBot running, ideally through the auto-start service |
| A recurring schedule skipped a run while the machine was asleep | Recurring schedules are not back-filled | This is expected. The loop computes the next occurrence from now, so a missed run simply waits for the next one |
| A one-time schedule fired late and behaved cautiously | It ran as a catch-up because it was more than two minutes late | This is expected. The agent is told how late it is and uses judgment, confirming with you for time-sensitive or irreversible actions |
| You cannot tell whether a schedule is armed | Nothing in the interface shows the next fire time | Watch the log with `tail -f logs/<run>/all.log | grep "\[SCHEDULER\]"`. You will see each `sleeping until` line and each fire. See [Scheduling](../../core/concepts/scheduling.md) |

## Files and workspace

The agent's own files live under `agent_file_system/` in the project folder.

| Symptom | Cause | Fix |
|---|---|---|
| A file the agent wrote is not where you expected | The agent works in its own workspace, not your shell's directory | Look under `agent_file_system/`. `EVENT.md` there records what the agent produced and observed |
| Data seems lost after an uninstall | Uninstall does not touch your data | Conversations, memory, and workspace files stay in the repository folder |

## Logs: where to look

When nothing above matches, the logs are the ground truth.

- **`logs/<run>/all.log`** is the full, time-ordered stream across all agents. Start here.
- **`logs/<run>/main.log`** is the main agent alone, without sub-agent noise.
- **`craftbot.log`** is the service log for startup and lifecycle, separate from the run logs.

Search for `ERROR` first, then read upward. The `[ACTION]` and `[REACT]` lines just before an error usually name what broke.

## Next

- [Integration issues](connections.md): connecting, listeners, and MCP servers
- [Provider issues](providers.md): authentication, models, rate limits, and media
- [Logs](../../core/concepts/logs.md): the file layout, subsystem tags, and grep recipes
