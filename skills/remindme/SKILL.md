---
name: remindme
description: "⏰ simple Telegram reminders for OpenClaw. cron, zero dependencies."
tags: [cron, reminders, productivity, schedule, telegram, discord, slack, whatsapp, signal]
metadata:
  openclaw:
    summary: "**Remind Me v2:** Schedule reminders anywhere. Natural language, native cron, zero dependencies."
    emoji: "bell"
user-invocable: true
command-dispatch: prompt
---

# Remind Me v2

Set reminders on **any channel** using natural language. No setup. No dependencies.

## Usage

```
/remindme drink water in 10 minutes
/remindme standup tomorrow at 9am
/remindme call mom next monday at 6pm
/remindme in 2 hours turn off oven
/remindme check deployment in 30s
/remindme every day at 9am standup
/remindme every friday at 5pm week recap
/remindme drink water in 10 minutes on telegram
/remindme standup tomorrow at 9am on discord
/remindme list
/remindme cancel <jobId>
```

## Agent Instructions

When the user triggers `/remindme`, determine the intent:

- **list** → call `cron.list` and show active reminder jobs.
- **cancel / delete / remove `<jobId>`** → call `cron.remove` with that jobId.
- **everything else** → create a new reminder (steps below).

---

### Step 1: Parse the Input (Structured Pipeline)

Extract three things: **WHAT** (the message), **WHEN** (the time), **RECURRENCE** (one-shot or recurring).

Follow this decision tree **in order** — stop at the first match:

#### Layer 1: Pattern Matching (works on any model)

Scan the input for these patterns. Match top-to-bottom, first match wins for WHEN:

**Relative durations** — look for `in <number> <unit>`:
| Pattern | Duration |
|---|---|
| `in Ns`, `in N seconds`, `in N sec` | N seconds |
| `in Nm`, `in N min`, `in N minutes` | N minutes |
| `in Nh`, `in N hours`, `in N hr` | N hours |
| `in Nd`, `in N days` | N * 24 hours |
| `in Nw`, `in N weeks` | N * 7 days |

**Absolute clock times** — look for `at <time>`:
| Pattern | Meaning |
|---|---|
| `at HH:MM`, `at H:MMam/pm` | Today at that time (or tomorrow if past) |
| `at Ham/pm`, `at HH` | Today at that hour |

**Named days** — look for `tomorrow`, `next <day>`, `on <day>`:
| Pattern | Meaning |
|---|---|
| `tomorrow` | Next calendar day, default 9am |
| `tonight` | Today at 8pm (or now+1h if past 8pm) |
| `next monday..sunday` | The coming occurrence of that weekday, default 9am |
| `on <day>` | Same as `next <day>` |

**Recurring** — look for `every <pattern>`:
| Pattern | Cron/Interval |
|---|---|
| `every Nm/Nh/Nd` | `kind: "every"`, `everyMs: N * unit_ms` |
| `every day at <time>` | `kind: "cron"`, `expr: "M H * * *"` |
| `every <weekday> at <time>` | `kind: "cron"`, `expr: "M H * * DOW"` |
| `every weekday at <time>` | `kind: "cron"`, `expr: "M H * * 1-5"` |
| `every weekend at <time>` | `kind: "cron"`, `expr: "M H * * 0,6"` |
| `every hour` | `kind: "every"`, `everyMs: 3600000` |

**Unit conversion table** (for `everyMs` and duration math):
| Unit | Milliseconds |
|---|---|
| 1 second | 1000 |
| 1 minute | 60000 |
| 1 hour | 3600000 |
| 1 day | 86400000 |
| 1 week | 604800000 |

#### Layer 2: Slang & Shorthand (common phrases)

If Layer 1 didn't match, check for these:
| Phrase | Resolves to |
|---|---|
| `in a bit`, `in a minute`, `shortly` | 30 minutes |
| `in a while` | 1 hour |
| `later`, `later today` | 3 hours |
| `end of day`, `eod` | Today 5pm |
| `end of week`, `eow` | Friday 5pm |
| `end of month`, `eom` | Last day of month, 5pm |
| `morning` | 9am |
| `afternoon` | 2pm |
| `evening` | 6pm |
| `tonight` | 8pm |
| `midnight` | 12am next day |
| `noon` | 12pm |

#### Layer 3: Event-Relative & Holidays (LLM reasoning required)

If Layers 1-2 didn't match, the input likely references an event or holiday. Use your knowledge to resolve:

**Holiday resolution** — when the user says "before/after/on <holiday>":
1. Identify the holiday and its **fixed date for the current year**.
2. Apply any offset: "3 days before Christmas" → Dec 25 minus 3 = Dec 22.
3. If the holiday has passed this year, use next year's date.

**Common fixed-date holidays** (reference table):
| Holiday | Date |
|---|---|
| New Year's Day | Jan 1 |
| Valentine's Day | Feb 14 |
| St. Patrick's Day | Mar 17 |
| April Fools | Apr 1 |
| US Independence Day | Jul 4 |
| Halloween | Oct 31 |
| Christmas Eve | Dec 24 |
| Christmas | Dec 25 |
| New Year's Eve | Dec 31 |

**Floating holidays** (vary by year — compute or look up):
- Thanksgiving (US): 4th Thursday of November
- Easter: varies (use your knowledge for the current year)
- Mother's Day (US): 2nd Sunday of May
- Father's Day (US): 3rd Sunday of June
- Labor Day (US): 1st Monday of September
- Memorial Day (US): Last Monday of May

**Cultural/religious events** (if referenced, use your knowledge):
- Ramadan, Eid al-Fitr, Eid al-Adha, Diwali, Hanukkah, Lunar New Year, etc.
- If you're unsure of the exact date, **ask the user to confirm** rather than guess.

**Event-relative patterns:**
| Pattern | Resolution |
|---|---|
| `N days before <event>` | event_date - N days |
| `N days after <event>` | event_date + N days |
| `the day before <event>` | event_date - 1 day |
| `the week of <event>` | Monday of event's week, 9am |
| `on <event>` | event_date, 9am |

#### Layer 4: Ambiguity — Ask, Don't Guess

If you still can't determine WHEN after all layers:
- **Ask the user** to clarify. Example: "I couldn't figure out the timing. When exactly should I remind you?"
- Never silently pick a default time.
- Never schedule a reminder you're not confident about.

### Step 2: Compute the Schedule

**Timezone rule:** ALWAYS use the user's **local timezone** (system timezone). Never default to UTC. If the user explicitly mentions a timezone (e.g. "at 9am EST"), use that instead.

**One-shot** → ISO 8601 timestamp with the user's local timezone offset.
- If the computed time is in the PAST, bump to the next occurrence.

**Recurring (cron)** → 5-field cron expression with `tz` set to the user's IANA timezone.
- `every day at 9am` → `expr: "0 9 * * *"`
- `every monday at 8:30am` → `expr: "30 8 * * 1"`
- `every weekday at 9am` → `expr: "0 9 * * 1-5"`

**Recurring (interval)** → `kind: "every"` with `everyMs` in milliseconds.
- `every 2 hours` → `everyMs: 7200000`

### Validation Checkpoint (before calling cron.add)

Before proceeding to Step 3, verify:
1. The computed timestamp is **in the future** (not the past).
2. The duration makes sense (e.g. "in 0 minutes" should be rejected).
3. For recurring: the cron expression or interval is valid (no `everyMs: 0`).
4. **Echo back** the parsed time to the user in the confirmation (Step 5) so they can catch errors.

### Step 3: Detect the Delivery Channel

Reminders are useless if the user never sees them. The delivery channel determines WHERE the reminder appears when it fires.

**Priority order:**

1. **Explicit override** — if the user says "on telegram" / "on discord" / "on slack" / "on whatsapp" in their message, use that channel.
2. **Current channel** — if the user is messaging from an external channel (Telegram, Discord, Slack, etc.), deliver there.
3. **Preferred channel** — if the user has a preferred reminder channel saved in MEMORY.md, use that.
4. **Last external channel** — use `channel: "last"` to deliver to the last place the user interacted externally.
5. **No external channel available** — if the user is on CLI/webchat and has NO external channels configured, **stop and ask**: "Where should I deliver this reminder? I need an external channel (Telegram, Discord, Slack, WhatsApp, Signal, or iMessage) since the CLI won't be open when the reminder fires."


### Step 4: Call `cron.add`

**One-shot reminder:**

```json
{
  "name": "Reminder: <short description>",
  "schedule": {
    "kind": "at",
    "at": "<ISO 8601 timestamp>"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "REMINDER: <the user's reminder message>. Deliver this reminder to the user now."
  },
  "delivery": {
    "mode": "announce",
    "channel": "<detected channel>",
    "to": "<detected target>",
    "bestEffort": true
  },
  "deleteAfterRun": true
}
```

**Recurring reminder:**

```json
{
  "name": "Recurring: <short description>",
  "schedule": {
    "kind": "cron",
    "expr": "<cron expression>",
    "tz": "<IANA timezone>"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "RECURRING REMINDER: <the user's reminder message>. Deliver this reminder to the user now."
  },
  "delivery": {
    "mode": "announce",
    "channel": "<detected channel>",
    "to": "<detected target>",
    "bestEffort": true
  }
}
```

**Fixed-interval recurring reminder** (e.g. "every 2 hours"):

```json
{
  "name": "Recurring: <short description>",
  "schedule": {
    "kind": "every",
    "everyMs": <interval in milliseconds>
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "RECURRING REMINDER: <the user's reminder message>. Deliver this reminder to the user now."
  },
  "delivery": {
    "mode": "announce",
    "channel": "<detected channel>",
    "to": "<detected target>",
    "bestEffort": true
  }
}
```

### Step 5: Confirm to User

After `cron.add` succeeds, reply with:

```
Reminder set!
"<reminder message>"
<friendly time description> (<ISO timestamp or cron expression>)
Will deliver to: <channel>
Job ID: <jobId> (use "/remindme cancel <jobId>" to remove)
```

---

## Rules

1. **ALWAYS use `deleteAfterRun: true`** for one-shot reminders. Omit it for recurring.
2. **ALWAYS use `delivery.mode: "announce"`** — without this, the user never sees the reminder.
3. **ALWAYS use `sessionTarget: "isolated"`** — reminders run in their own session.
4. **ALWAYS use `wakeMode: "now"`** — ensures immediate delivery at the scheduled time.
5. **ALWAYS use `delivery.bestEffort: true`** — prevents job failure if delivery has a transient issue.
6. **NEVER use `act:wait` or loops** for delays longer than 1 minute. Cron handles timing.
7. **NEVER deliver to localhost/webchat/CLI** — the user won't be there when the reminder fires. If on CLI with no external channels, ask the user where to deliver.
8. **Always use the user's local timezone** (system timezone). Never default to UTC. If MEMORY.md has a timezone override, use that instead.
9. **For recurring reminders**, do NOT set `deleteAfterRun`.
10. **Always return the jobId** so the user can cancel later.
11. **If the user says "on telegram/discord/slack/etc"**, override the auto-detected channel with the explicit one.

## Troubleshooting

- **Reminder didn't fire?** → `cron.list` to check. Verify gateway was running at the scheduled time.
- **Delivered to wrong chat?** → Use explicit chat/channel ID, not `"last"`.
- **Too many old jobs?** → Install the Janitor (see `references/TEMPLATES.md`).
- **Recurring job keeps delaying?** → After consecutive failures, cron applies exponential backoff (30s → 1m → 5m → 15m → 60m). Backoff resets after a successful run.

## References

See `references/TEMPLATES.md` for copy-paste templates and the Janitor auto-cleanup setup.
