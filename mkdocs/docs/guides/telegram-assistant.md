# Telegram assistant

This guide connects CraftBot to a Telegram bot so you drive the agent from your phone. When you finish, you can send a task from Telegram, watch it run while you are away from the desk, and get the result back in the same chat, including files as attachments. The browser does not need to be open, and the agent stays reachable because it runs as a background service.

This is the recipe. For the full Telegram action list and configuration reference, see [Telegram (Bot)](../integrations/telegram-bot.md).

## What you need

Handle these before Step 1.

| Requirement | How to get it |
|---|---|
| A working CraftBot | Finish the [Quickstart](../start/quickstart.md) so the agent replies to `hello` in the browser |
| CraftBot in service mode | Run `python craftbot.py install` so the agent stays running when the browser is closed; see [Service mode](../start/service-mode.md) |
| A Telegram account | Any personal account, used once to talk to @BotFather and to chat with your bot |
| A Telegram bot token | Created in the next step with @BotFather, in the form `123456:ABC...` |

Service mode matters here. A bot only reacts while CraftBot is running, so if the agent lives on a laptop that sleeps, messages you send while it is asleep are picked up when it next starts, not the moment you send them. For an assistant you can reach any time, run it on a machine that stays awake. Both cases are covered in [Service mode](../start/service-mode.md).

## Step 1: create the bot

Create the bot account in Telegram with @BotFather. The full walkthrough is in [Telegram (Bot) setup](../integrations/telegram-bot.md#setup). The short version is:

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, then pick a display name and a username ending in `bot`.
3. Copy the token BotFather replies with. It looks like `123456:ABC...`.

Keep the token private. Anyone who has it controls your bot.

## Step 2: connect it to CraftBot

Give the token to CraftBot, then open a chat so the bot has somewhere to reply.

1. In the browser, open **Settings → Integrations → Telegram Bot**, paste the token into **Bot Token**, and connect. From chat, `/telegram_bot login <bot_token>` does the same thing.
2. In Telegram, open your new bot and send `/start`. A bot cannot message a person who has never started it, so this first message is what gives the agent a chat to reply into.
3. Confirm the link with `/telegram_bot status`. It reports the connected bot username.

CraftBot validates the token, stores it locally, and starts a listener that polls Telegram for new messages. From now on, anything you send the bot reaches the agent.

**Checkpoint:** `/telegram_bot status` shows your bot username, and you have sent `/start` to the bot at least once.

## Step 3: how Telegram messages reach the agent

A Telegram message is not a separate, cut-down chat channel. It enters the agent the same way a browser message does, so everything you already know about runs applies.

Here is the path a message takes:

1. **The listener receives it.** While connected, CraftBot long-polls Telegram for new messages. Only messages that carry text are forwarded, and each is dispatched once.
2. **It becomes a trigger.** The incoming message is turned into a `user_message` trigger, the same durable record a browser message creates. Triggers are written to disk before they run, so a message is not lost if CraftBot restarts mid-handling. See [Triggers](../core/concepts/triggers.md).
3. **It lands in the main session.** Platform messages go to the agent's main session, and if several arrive while it's busy they fold into one turn. See [Sessions](../core/concepts/task-sessions.md).
4. **The run works the normal way.** The agent scales its process to the request: a small ask gets a direct answer; real work gets requirements, a todo plan, and step-by-step execution — identically to a request from the browser. See [Runs](../core/modes/index.md).
5. **Replies come back to Telegram.** The run records that your message came from Telegram, so its updates and results go back to the chat you wrote from, not to the browser.

Two consequences are worth stating plainly. Long runs keep working after you lock your phone, because the work lives in the agent, not in the chat window, and you get the result when it is done. And work started from Telegram can send you progress updates and the final answer in that same chat as it goes.

## Step 4: send your first task from Telegram

Open your bot in Telegram and send a request with a concrete deliverable, the same way you would in the browser:

```
Research the current state of solid-state batteries,
write a one-page summary, and send it back to me here as a file.
```

Watch what happens:

1. The agent acknowledges and starts working. A request this size gets a requirement contract and a live todo list.
2. It runs actions to research and write the summary. You can open the browser later to see the full activity view, but you do not have to.
3. When it finishes, it sends the summary into the Telegram chat and, because you asked for a file, attaches it as a document.

You can steer the work from your phone while it runs. Send a follow-up like:

```
Focus on automotive use, not consumer electronics.
```

Your message arrives in the same session, folds into the agent's next turn, and the agent adjusts course. The mechanics are in [Sessions](../core/concepts/task-sessions.md).

**Checkpoint:** you sent work from Telegram, received the summary and the attached file in the chat, and a follow-up message changed what the agent did.

## Step 5: tune it for personal use

For a personal assistant you talk to alone, restrict the bot to your own direct messages and let the agent reach out to you on its own.

**Direct messages only.** In **Settings → Integrations → Telegram Bot**, turn on **Private DMs only** (`self_messages_only`). With it on, only messages from one-to-one private chats reach the agent. Group, supergroup, and channel messages are dropped before dispatch. This keeps the bot focused on you and ignores any group it happens to be in. The listener re-reads this setting on every message, so the change applies without reconnecting.

**Chat versus work over chat.** Nothing changes on Telegram. A plain question ("what's on my plate today?") gets a direct answer. A request with a deliverable gets the full structured treatment. You do not send commands to switch — you phrase the message as a chat or as work, and the agent scales its process accordingly. See [Runs](../core/modes/index.md).

**Let the agent message you first.** With [proactive mode](../core/modes/proactive.md) on, the agent runs recurring work on a schedule and can push the result to you in Telegram. Set up a recurring task by asking in plain language, for example:

```
Every weekday at 8am, summarize my unread email and send it to me on Telegram.
```

The agent adds this to its recurring registry and sends the summary to your bot chat on schedule. Proactive work only fires while CraftBot is running, which is the other reason Step 0 put it in service mode. A bot can only send into a chat you have already started, so proactive updates arrive in the chat where you first sent `/start`. If you want a true self-messaging inbox that the agent can open on its own, connect your personal account with [Telegram (User)](../integrations/telegram-user.md) instead.

## Using it in a group chat

You can also drop the bot into a group so a team shares one agent. This is optional, and it works differently from your private chat.

1. Make sure **Private DMs only** is off, or the agent will ignore every group message.
2. Add the bot to the group like any other member.
3. In @BotFather, disable Privacy Mode for the bot. With Privacy Mode on, a bot only receives messages that address it directly, so it will not see normal group chatter. Re-add the bot to the group after changing this.

In a busy group you rarely want the agent reacting to every line. Two behaviors help. Address the bot directly (mention it or reply to its message) so it is clear a message is for it. And the agent can deliberately end a turn silently (`end_turn`) for messages that need no response, which is exactly the group case where most messages are people talking to each other, not to the agent. See [Quick requests](../core/modes/simple-task.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot never responds to anything | CraftBot is not running | `python craftbot.py status`, then `start`. A bot only reacts while the service is up |
| "Invalid bot token" at login | Token is wrong or was revoked in @BotFather | Copy the token again from @BotFather and run `/telegram_bot login <token>` |
| Messages you send are ignored, no error | `getUpdates` conflict: a webhook is registered, which is mutually exclusive with polling | Run `delete_telegram_webhook`, then send another message |
| Replies never arrive in Telegram | You never sent `/start`, so the bot has no chat to reply into | Open the bot in Telegram and send `/start`, then retry |
| Agent replies in DMs but is silent in a group | Privacy Mode is on, or **Private DMs only** is on | Disable Privacy Mode in @BotFather and re-add the bot; turn off **Private DMs only** in Settings |
| Bot sees group messages but replies to almost none | Working as intended: it ignores messages not addressed to it | Mention the bot or reply to its message so the request is clearly for it |

## Next

- [Telegram (Bot)](../integrations/telegram-bot.md): the full action list, configuration, and setup reference
- [Telegram (User)](../integrations/telegram-user.md): connect your own account for a personal self-messaging inbox
- [Proactive mode](../core/modes/proactive.md): recurring tasks the agent runs and reports on its own
- [Sessions](../core/concepts/task-sessions.md): where messages land and how runs work, in the browser and over chat
