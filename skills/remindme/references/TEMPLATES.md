# Cron Templates for Remindme

## One-Shot Reminder (Telegram)

```json
{
  "name": "Reminder: <description>",
  "schedule": {
    "kind": "at",
    "at": "2026-02-11T23:00:00Z"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "⏰ REMINDER: <message>. Deliver this reminder now."
  },
  "delivery": {
    "mode": "announce",
    "channel": "telegram",
    "to": "<chatId>",
    "bestEffort": true
  },
  "deleteAfterRun": true
}
```

## One-Shot Reminder (Discord)

```json
{
  "name": "Reminder: <description>",
  "schedule": {
    "kind": "at",
    "at": "2026-02-11T23:00:00Z"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "⏰ REMINDER: <message>. Deliver this reminder now."
  },
  "delivery": {
    "mode": "announce",
    "channel": "discord",
    "to": "channel:<channelId>",
    "bestEffort": true
  },
  "deleteAfterRun": true
}
```

## Recurring Reminder (Any Channel)

```json
{
  "name": "Daily: <description>",
  "schedule": {
    "kind": "cron",
    "expr": "0 9 * * *",
    "tz": "Africa/Cairo"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "⏰ RECURRING: <message>"
  },
  "delivery": {
    "mode": "announce",
    "channel": "last",
    "bestEffort": true
  }
}
```

## The Janitor (Auto-Cleanup)

Install this once to clean up expired one-shot reminders every 24 hours:

```json
{
  "name": "Daily Cron Cleanup",
  "schedule": {
    "kind": "every",
    "everyMs": 86400000
  },
  "sessionTarget": "isolated",
  "wakeMode": "next-heartbeat",
  "payload": {
    "kind": "agentTurn",
    "message": "Time for the 24-hour remindme cleanup. List all cron jobs. Only delete jobs whose name starts with 'Reminder:' that are disabled (enabled: false) and have lastStatus: ok (finished one-shots). Do NOT delete any jobs that don't start with 'Reminder:' — those belong to other skills. Do NOT delete active recurring jobs (name starts with 'Recurring:'). Log what you deleted."
  },
  "delivery": {
    "mode": "none"
  }
}
```

## Timezone Reference

Common timezone identifiers:
- `Africa/Cairo` (GMT+2)
- `America/New_York` (EST/EDT)
- `America/Los_Angeles` (PST/PDT)
- `Europe/London` (GMT/BST)
- `Asia/Tokyo` (JST)

Always confirm the user's timezone before scheduling absolute-time reminders.
