# Set up a proactive daily briefing

By the end of this guide, CraftBot sends you a short summary every weekday morning: your unread email from the last day and your calendar for the day ahead, delivered to your phone through a messaging integration. You set it up once by asking in chat, test it on demand, and then leave it running. Nothing else to remember. The agent gathers the inputs, writes the summary, and sends it while you are still waking up.

This guide assumes you have a working CraftBot install and can chat with the agent. If not, complete the [Quickstart](../start/quickstart.md) first.

## What you need

| Requirement | Why | Set it up |
|---|---|---|
| CraftBot in service mode | Schedules only fire while CraftBot is running. Service mode keeps it alive in the background so the 7:30am briefing fires even when your laptop is closed or the browser tab is shut. | [Service mode](../start/service-mode.md) |
| A connected email integration | This is the source of your unread mail. Use Gmail or Outlook. | [Gmail](../integrations/gmail.md), [Outlook](../integrations/outlook.md) |
| A connected calendar (optional) | Adds today's events to the briefing. Google Calendar is the common choice; Outlook already carries calendar. | [Google Calendar](../integrations/google-calendar.md) |
| A messaging integration | This is where the briefing lands. This guide uses Telegram so the summary reaches your phone. | [Telegram (Bot)](../integrations/telegram-bot.md) |

Connect all of these before you create the schedule. A schedule that references a disconnected integration fires on time but produces nothing useful.

## Step 1: connect your inputs

The inputs are the mailbox and calendar the agent reads each morning.

1. Connect your mailbox. Open **Settings → Integrations** and connect [Gmail](../integrations/gmail.md) or [Outlook](../integrations/outlook.md). Follow that integration's setup page to authorize the account.
2. Connect your calendar, if you want events in the briefing. With Gmail, add [Google Calendar](../integrations/google-calendar.md). With Outlook, the calendar comes with the mailbox, so there is nothing extra to connect.
3. Confirm both are linked. Run `/cred status` in chat. Each connected integration appears in the list.

Check it worked by asking for the data directly, before any schedule exists:

```
Summarize my unread email from the last 24 hours, and list today's calendar events.
```

The agent opens a task, reads your mailbox and calendar, and replies with the summary in chat. If this reply is empty or errors, fix the integration now. A schedule cannot pull data the agent cannot reach by hand.

## Step 2: connect the output channel

The output channel is where the finished briefing is delivered. This guide uses a Telegram bot so it arrives on your phone.

1. Create a bot with @BotFather and connect it in **Settings → Integrations → Telegram Bot**. The full walkthrough is on the [Telegram (Bot)](../integrations/telegram-bot.md) page.
2. In Telegram, send `/start` to your bot so it has a chat to reply into. A bot cannot message you until you have started it.
3. Note the numeric `chat_id` of that chat, or plan to reply to the bot once so the agent learns where to send.

Confirm delivery works on its own:

```
Send "briefing test" to me on Telegram.
```

The message should arrive in your Telegram chat. If it does not, resolve it using the [Telegram troubleshooting table](../integrations/telegram-bot.md#troubleshooting) before continuing. Delivery is the part most likely to fail silently at 7:30am, so prove it now.

## Step 3: create the scheduled briefing

Now combine the inputs and the output into one recurring task. Ask for it in plain language, in a single message:

```
Every weekday at 7:30am, summarize my unread email from the last 24 hours
and today's calendar events, then send it to me on Telegram.
```

This becomes a [scheduled task](../core/concepts/scheduling.md): a named instruction plus a schedule expression, stored so the scheduler can fire it at the right moment.

One detail matters here. The scheduler does not understand freeform phrases. "Every weekday", "each morning", and "daily at 7:30" are all rejected by the schedule parser. The only accepted patterns are a fixed set (immediate, one-time, daily, weekly, interval, and 5-field cron), listed in full under [schedule expressions](../core/concepts/scheduling.md#schedule-expressions). "Weekdays only at a set time" is not one of the natural-language patterns, so it can only be written as cron.

You do not write that cron yourself. The agent translates your request into a valid expression when it calls the `schedule_task` action. For "every weekday at 7:30am" the correct translation is:

```
30 7 * * 1-5
```

That reads as minute 30, hour 7, any day of month, any month, weekdays Monday through Friday. If you had asked for 7am instead, the agent would record `0 7 * * 1-5`. All times are the local clock of the machine CraftBot runs on.

Verify the translation rather than trusting it. Ask:

```
What do you have scheduled?
```

The agent runs `scheduled_task_list` and shows every schedule with its ID, its schedule expression, whether it is enabled, and its last and next run times. Read the expression on your new briefing. It should be `30 7 * * 1-5`. If instead you see a daily-only expression like `every day at 7:30am`, the weekday restriction was dropped. Tell the agent "the briefing should run weekdays only, Monday to Friday", and it will re-record the schedule as cron.

## Step 4: test it immediately

Do not wait until tomorrow morning to find out whether the briefing works. Run it once, right now:

```
Run my morning briefing now.
```

The agent executes the same instruction as a one-time immediate task. Immediate is one of the accepted schedule types, so the agent can fire the briefing on demand without disturbing the recurring schedule. Within a moment the summary should land in your Telegram chat exactly as it will every weekday.

Check the delivered message:

- The unread-email section reflects your actual inbox.
- Today's events are listed, if you connected a calendar.
- The message arrived on your phone, not just in the browser chat.

If the on-demand run is correct, the scheduled run will be too, because it runs the same instruction. If it is wrong, fix it here where you get instant feedback, then re-test.

## Step 5: confirm the recurring schedule

With the content proven, confirm the recurring schedule is in place and enabled:

```
Show my scheduled tasks.
```

On the briefing row, check three things in the `scheduled_task_list` output:

- **Schedule expression** is `30 7 * * 1-5`.
- **Enabled** is true. A schedule created paused never fires.
- **Next run** is the next upcoming weekday at 7:30am.

If all three are right, you are done. The briefing will fire tomorrow morning, and every weekday after, for as long as CraftBot is running. Recurring schedules are not back-filled, so a morning CraftBot happens to be offline is simply skipped and the next day's 7:30am proceeds as normal. This is the reason Step 1 asked for [service mode](../start/service-mode.md).

## Step 6: refine and maintain

The briefing is a normal scheduled task, so you adjust it the same way you made it, by asking.

**Change the time.** "Move my morning briefing to 8am." The agent re-records the schedule as `0 8 * * 1-5`.

**Add a source.** "Also include my unread Slack mentions in the morning briefing." The agent updates the instruction. Connect the [integration](../integrations/index.md) first, the same way you connected email.

**Pause it.** "Pause the morning briefing." The agent calls `schedule_task_toggle`, which disables the schedule by ID. The entry stays in your config and its loop stops, so no briefing fires until you say "resume the morning briefing". To remove it for good, say "delete the morning briefing", which runs `remove_scheduled_task`.

**Scheduled task versus proactive mode.** What you built is a plain scheduled task: it does one fixed thing at one fixed time, and nothing else. It is predictable and self-contained. [Proactive mode](../core/modes/proactive.md) is a different system. There the agent plans and runs recurring work on its own initiative under permission tiers, and asks for your consent before adding a recurring habit. A daily briefing does not need proactive mode. Reach for proactive mode when you want the agent to decide *what* to work on, not just *when* to run one instruction you already wrote.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Briefing never arrives in the morning | CraftBot was not running at 7:30am | Run CraftBot in [service mode](../start/service-mode.md) so schedules fire while your laptop is closed. Confirm with `python craftbot.py status`. |
| Briefing fires every day, including weekends | Schedule recorded as daily, not weekday cron | Run `scheduled_task_list` and check the expression. If it is not `30 7 * * 1-5`, tell the agent to restrict it to weekdays Monday through Friday. |
| Briefing fires at the wrong hour | Cron uses the machine's local clock, or the time was mistranslated | Confirm the machine's timezone, then re-state the time you want and re-check the expression in `scheduled_task_list`. |
| Summary arrives but is empty | No unread mail in the window, or the wrong account is connected | Ask the agent to summarize your unread email directly. If that is also empty, reconnect the correct mailbox in **Settings → Integrations**. |
| Summary is missing calendar events | No calendar connected, or the wrong calendar | Connect [Google Calendar](../integrations/google-calendar.md), or confirm the Outlook account holds the calendar you mean. |
| Briefing runs but nothing reaches your phone | Telegram not connected, or the bot was never started | Run `/telegram_bot status`. Send `/start` to your bot in Telegram. See the [Telegram troubleshooting](../integrations/telegram-bot.md#troubleshooting) table. |
| Schedule is in the list but never fires | The schedule is disabled | Check the enabled state in `scheduled_task_list`. Say "resume the morning briefing" to re-enable it. |

## Next

- [Scheduling](../core/concepts/scheduling.md): every schedule expression, one-time versus recurring behavior, and the schedule actions.
- [Proactive mode](../core/modes/proactive.md): let the agent plan and run recurring work on its own, beyond a single fixed instruction.
- [Telegram assistant](telegram-assistant.md): drive the agent hands-free from Telegram, not just receive from it.
- [Service mode](../start/service-mode.md): keep CraftBot alive so every scheduled briefing fires.
