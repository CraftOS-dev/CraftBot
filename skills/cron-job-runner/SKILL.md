---
name: cron-job-runner
description: Run the cron jobs from PROACTIVE.md that the scheduler hands to this run (each fires at its own set time), delegating each job to a general_agent sub-agent where its tools fit, and report the result in one message.
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - web_research
---

# Cron Job Runner

Skill for running scheduled cron jobs. Every cron job in PROACTIVE.md has its own slot (hourly at :MM, daily at HH:MM, weekly on a day at HH:MM, monthly on a date at HH:MM). The scheduler fires this run when one or more jobs reach their slot, or when a slot was missed while CraftBot was off.

## Trigger Context

Your instruction lists exactly the jobs to run now, each with:
- its name and id, its schedule, and its tier (notify or silent)
- its instruction
- conditions to check first, if it has any
- a "Late" note when it is running well after its slot

The scheduler has ALREADY selected these jobs and recorded them as run. Do not call `cron_job_list` to work out what is due, do not re-check their time or day fields, and do not schedule them "for later". After each job, record its outcome with `cron_job_update(job_id, add_outcome={"result": "...", "success": true/false})`.

---

## CRITICAL: Automatic Run (Override Standard Task Rules)

This run starts on its own in the user's main chat, not from a user message:

- **NO acknowledgement**: do not acknowledge the trigger or post progress updates.
- **Your run-ending `send_message` is the result.** Put everything the user should see in that ONE message.
- **Nothing to report → `end_turn`.** If every job was silent (tier 0) or skipped and nothing needs the user's attention, end with `end_turn`.
- **Never wait for the user.** Do not end on a question that needs an answer before the job can finish. If a job needs the user (a login, a decision), say so in the final message and stop that job.

---

## Two Ways to Run a Job

### DELEGATED (default)
Hand the job to a general-purpose sub-agent:

```
spawn_subagent(
  agent_type="general_agent",
  query="[The job's instruction, rewritten to stand alone: every path, URL, criterion and the shape of the result you need back]"
)
```

It works in its own context and returns one `result`, so the job's tool output stays out of this chat.

**Use DELEGATED when** the job's work fits general_agent's tools: files, shell / PowerShell, `web_search`, `web_fetch`, `http_request`.

- The `query` must be self-contained: the sub-agent sees nothing of this chat, your memory or your skills.
- Independent jobs: one `spawn_subagent` call per job, all in the same decision, so they run in parallel.
- The sub-agent never messages the user. You send the one final message.

### INLINE
Do the job yourself in this run.

**Use INLINE when** the job needs something general_agent does not have:
- A connected app (email, calendar, messaging): load its action set with `add_action_sets`
- `memory_search`, or the proactive actions
- A website it must sign in to or click through (Mini Browser, below)

### Jobs That Operate a Website (Mini Browser)

Reading public pages works with `web_search` / `web_fetch`. A job that must USE a site (sign in, open an account page, click through, fill a form) needs the Mini Browser (action set `mini_browser`, a real browser with the user's saved logins). general_agent has no browser, so run these INLINE:

- `add_action_sets(["mini_browser"])` (their schemas arrive in your event stream), then the `mini_browser_*` actions next turn (`mini_browser_navigate`, then act on the numbered elements each result returns; `mini_browser_login` signs in with a saved login).
- A login that isn't saved, a CAPTCHA or a 2FA prompt → stop that job and say in the final message what is needed.

---

## Tiered Permission Model

Every job in your instruction is marked notify (tier 1) or silent (tier 0).

```
Tier 0 - Silent:
  - Search and summarize information
  - Detect anomalies and patterns
  - Draft recommendations internally
  - Read files and analyze data
  - Report only if the job's instruction asks for it, or something needs attention

Tier 1 - Notify:
  - Do the job, then report the result in the final message
  - Share analysis results, a proposed plan or a draft
```

Actions that send messages to other people, spend money or change external accounts are never done in a cron job run unless the job's instruction explicitly says to. When you delegate, put that limit in the `query`.

## Evaluation Rubric

Score 1-5 for each dimension to decide whether running a job right now is worth it:

```
1. IMPACT (How significant is the outcome?)
   1 = Negligible impact
   2 = Minor improvement
   3 = Moderate benefit
   4 = Significant positive outcome
   5 = Critical/transformative impact

2. RISK (What could go wrong?)
   1 = High risk, potential for serious harm
   2 = Moderate risk, some potential issues
   3 = Low risk, manageable concerns
   4 = Very low risk, unlikely issues
   5 = No risk, completely safe

3. COST (Resources/effort required)
   1 = Very high cost/effort
   2 = Significant resources needed
   3 = Moderate effort required
   4 = Low cost/minimal effort
   5 = Negligible resources needed

4. URGENCY (How time-sensitive?)
   1 = Not urgent, can wait indefinitely
   2 = Low urgency, within weeks
   3 = Moderate urgency, within days
   4 = High urgency, within hours
   5 = Critical urgency, immediate action needed

5. CONFIDENCE (User acceptance likelihood)
   1 = Very unlikely to accept
   2 = Unlikely to accept
   3 = Uncertain/50-50
   4 = Likely to accept
   5 = Very likely/certain to accept

Decision Threshold:
- Total score >= 18: Strong candidate for execution
- Total score 13-17: Consider execution, may need user input
- Total score < 13: Skip this run (say so in the final message if the job is tier 1)
```

## Workflow

### Step 1: Read the Job List

Take the jobs from your instruction, in order. Read MEMORY.md, USER.md or other files only as far as a job needs them.

### Step 2: Check Each Job

1. **Conditions**: if a job lists conditions, check them first and skip the job if one does not hold:
   - `market_hours_only`: skip outside 9:30 AM - 4:00 PM on weekdays
   - `weekdays_only`: skip on Saturday and Sunday
   - `user_available`: skip if the user has not been active recently
   - Custom conditions as described
2. **Late note**: a job running late may no longer make sense (a "good morning" brief at 9 PM). Skip it and say so, or adapt it.
3. **Rubric**: score it; skip below 13.

### Step 3: Run Each Job

Choose DELEGATED or INLINE. Spawn every delegated job in the same decision, then do the INLINE ones. If a job fails, note why and continue with the next one.

### Step 4: Record Outcomes

For every job in the list (done, skipped or failed): `cron_job_update(job_id, add_outcome={"result": "[one line: what happened]", "success": true/false})`.

### Step 5: Finish

- Something to report → ONE `send_message` (no `continue_work`) with a short section per job that has news: what was done, the findings, anything that needs the user.
- Nothing to report → `end_turn`.

## Rules

- **One final message**: everything the user should see goes into the run-ending `send_message`
- **No progress messages**: do not acknowledge the trigger or post status updates
- **Silent on nothing**: end with `end_turn` when no job has news
- **Never wait for the user**: report what is needed instead of asking and waiting
- **Do not re-schedule**: the scheduler already chose these jobs and recorded them as run; you only record each outcome
- **Delegate by default**: run a job INLINE only when general_agent lacks what it needs
- **Handle failures gracefully**: note the failure, record it as the job's outcome and continue with the next job

## Example Flows

### Example 1: INLINE Execution (Daily Briefing)

1. Instruction lists `daily_morning_briefing` (daily at 07:00, notify)
2. Score: Impact=4, Risk=5, Cost=4, Urgency=3, Confidence=4 = 20 (execute)
3. It needs the calendar (a connected app), so INLINE: gather weather, calendar and jobs
4. `cron_job_update("daily_morning_briefing", add_outcome={"result": "Sent the morning briefing", "success": true})`
5. Final `send_message` with the briefing

### Example 2: DELEGATED Execution (Complex Analysis)

1. Instruction lists `weekly_code_review` (weekly on Sunday at 17:00, notify)
2. Score: Impact=4, Risk=5, Cost=3, Urgency=2, Confidence=4 = 18 (execute)
3. Files and shell only, so DELEGATED: `spawn_subagent(agent_type="general_agent", query="Review the git commits of the past 7 days in C:\\path\\to\\repo (git log, git diff). Do not change any file. Return: a list of risky changes with file paths, and anything that looks unfinished.")`
4. `cron_job_update("weekly_code_review", add_outcome={"result": "Reviewed 14 commits, 2 risky changes", "success": true})`
5. Final `send_message` with the findings

### Example 3: Silent Job

1. Instruction lists `hourly_inbox_scan` (hourly at :00, silent)
2. Email is a connected app, so INLINE; nothing urgent found
3. `cron_job_update("hourly_inbox_scan", add_outcome={"result": "Nothing urgent", "success": true})`
4. `end_turn`

## Allowed Actions

`send_message`, `end_turn`, `spawn_subagent`, `memory_search`, `read_file`,
`web_search`, `web_fetch`, `update_todos`, `cron_job_update` (only
`add_outcome`, for the jobs in this run), `add_action_sets` (for the
connected apps a job needs), and for website jobs the `mini_browser_*`
actions (see "Jobs That Operate a Website")

## Forbidden Actions

Direct file writes to PROACTIVE.md, changing a job with `cron_job_update`
`updates`, and `cron_job_add` / `cron_job_remove` /
`heartbeat_checklist_update` (changes need the user's request)
