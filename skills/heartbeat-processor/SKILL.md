---
name: heartbeat-processor
description: Go through the Heartbeat checklist from PROACTIVE.md on each heartbeat tick, delegating each check to a general_agent sub-agent where its tools fit, act only on what needs attention, and report in one message or end silently.
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - web_research
---

# Heartbeat Processor

Skill for the heartbeat. Every heartbeat tick (every 30 minutes by default, set in Settings > Proactive), if the Heartbeat checklist in PROACTIVE.md is not empty, CraftBot starts this run. Your instruction contains the checklist exactly as the user wrote it.

The heartbeat is for keeping an eye on things ("Check my inbox for urgent client email", "Tell me if the deploy fails"). Work that must happen at a set time is a cron job, not a heartbeat item.

---

## CRITICAL: Automatic Run (Override Standard Task Rules)

This run starts on its own in the user's main chat, not from a user message:

- **Most heartbeats should end with `end_turn`.** If nothing on the checklist needs the user right now, end with `end_turn` and send nothing.
- **Something needs the user → ONE `send_message`.** Cover every item that needs attention in that one message, briefly.
- **NO acknowledgement**: do not acknowledge the heartbeat or post progress updates.
- **Never wait for the user.** If an item needs a decision or a login, say so in the final message and stop.

---

## Workflow

1. **Read the checklist** in your instruction. Each line is one thing to check.
2. **Check each item now.** Keep each check quick.
   - **Delegate** an item to a general-purpose sub-agent when its tools cover the check (files, shell / PowerShell, `web_search`, `web_fetch`, `http_request`): `spawn_subagent(agent_type="general_agent", query="...")`. One call per item, all in the same decision. Each `query` must stand alone (the sub-agent sees nothing of this chat) and ask for a short verdict back: what changed, and whether it needs the user.
   - **Check it yourself** when it needs a connected app (email, calendar, messaging) or memory: load the matching action set with `add_action_sets`. general_agent has none of those.
   - A site you must sign in to or click through needs the Mini Browser (general_agent has no browser): `add_action_sets(["mini_browser"])`, then `mini_browser_navigate` (`mini_browser_login` signs in with a saved login). A login that isn't saved, a CAPTCHA or a 2FA prompt: say what is needed in the final message instead.
3. **Decide whether it needs attention.** Report only what is new, urgent or asked for by the item. Do not repeat something you already reported: check this chat's earlier heartbeat messages and `memory_search`.
4. **Finish:**
   - Something to report → ONE `send_message` (no `continue_work`), one short section per item that needs attention.
   - Nothing to report → `end_turn`.

## Rules

- **Silence is the normal outcome**: a heartbeat that finds nothing ends with `end_turn`
- **One final message** when something does need the user
- **No new commitments**: do not send messages to other people, spend money or change external accounts unless the checklist item explicitly says to. When you delegate, put that limit in the `query`.
- **Do not change the checklist** (or cron jobs) yourself; changes need the user's request
- **Handle failures quietly**: if a check fails, mention it only when it keeps the user from something they asked to watch

## Example Flows

### Example 1: Nothing new

1. Checklist: "- Check my inbox for urgent email from clients"
2. Email is a connected app, so you check it yourself; nothing urgent since the last report
3. `end_turn`

### Example 2: Something needs attention

1. Checklist: "- Check my inbox for urgent email from clients" and "- Tell me if the nightly build failed"
2. Delegate the build check (`spawn_subagent(agent_type="general_agent", query="Fetch https://ci.example.com/api/nightly/latest with http_request. Do not change anything. Return: passed or failed, and the failing step if any.")`) and check the inbox yourself
3. A client asked for a contract change today; the build passed
4. Final `send_message`: one line about the client email and what it asks for

## Allowed Actions

`send_message`, `end_turn`, `spawn_subagent`, `memory_search`, `read_file`,
`grep_files`, `web_search`, `web_fetch`, `add_action_sets` (for the
integrations a checklist item needs), `update_todos`

## Forbidden Actions

Direct file writes to PROACTIVE.md, `heartbeat_checklist_update`, and the
`cron_job_*` actions (changes need the user's request)
