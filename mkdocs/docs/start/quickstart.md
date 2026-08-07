# Quickstart

This page takes you from a fresh clone to a completed first piece of real work, with a checkpoint after every step so you always know whether you're on track. Budget 10–15 minutes.

**Who this is for:** anyone setting up CraftBot for the first time. If you've already installed and can chat with the agent, skip to [Step 4](#step-4-run-your-first-real-task).

## Where to start

Match your situation to a starting point:

| Your situation | Do this |
|---|---|
| Fresh machine, want the full experience | Follow all six steps below |
| Already installed, agent won't reply | [Step 2: connect a provider](#step-2-connect-a-model-provider) |
| Agent replies, want to see real work | [Step 4: first real task](#step-4-run-your-first-real-task) |
| No Node.js and can't install it | Steps below, but launch with `python run.py --cli` |
| Don't want to pay for an API | Run [Ollama](https://ollama.com) locally, pick the **Remote** provider in Step 2 — zero tokens spent |

**Get a normal chat working before you add anything else.** If the agent can't answer `hello`, connecting Slack or scheduling work will not work either. Fix the basics first.

## Step 1: Install and launch

```bash
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
python craftbot.py install
```

This installs dependencies, registers auto-start, launches CraftBot in the background, and opens `http://localhost:7925` in your browser. If you'd rather run in the foreground (nothing registered, stops when you close the terminal), use `python install.py` followed by `python run.py` instead. Both paths are covered in detail on the [Install](install.md) page.

**Checkpoint:** your browser shows the CraftBot interface. First launch takes longer because the frontend builds once. If the page doesn't load, wait a minute and refresh, then check `python craftbot.py logs`.

## Step 2: Connect a model provider

CraftBot has no bundled model, so it needs one from you. The first launch shows the [onboarding wizard](onboarding.md), whose first two steps are exactly this: pick a provider, paste a key. If you skipped the wizard, use the `/provider` command in chat or **Settings → Model**.

The most common choices:

| Provider | Key | Notes |
|---|---|---|
| **Anthropic Claude** | `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com) | Default provider |
| **OpenAI** | `OPENAI_API_KEY` from [platform.openai.com](https://platform.openai.com) | Also supports ChatGPT Plus/Pro/Team **subscription login** instead of a key, see [Subscription authentication](../core/providers/subscription-auth.md) |
| **Google Gemini** | `GOOGLE_API_KEY` from [AI Studio](https://aistudio.google.com) | |
| **Ollama (local)** | No key. Point CraftBot at your Ollama server (default `http://localhost:11434`) | Free; quality depends on the model you run |
| **xAI Grok** | `XAI_API_KEY` | Also supports SuperGrok subscription login |

These five are a subset. CraftBot supports 13 providers (DeepSeek, Moonshot, MiniMax, GLM, OpenRouter, AWS Bedrock, and more), all listed with their key names and default models in [LLM providers](../core/providers/llm.md).

To set the provider from chat:

```
/provider                      # show current provider and options
/provider anthropic sk-ant-... # switch provider and set the key in one line
```

Keys are stored in CraftBot's local settings file (`app/config/settings.json`) and stay on your machine.

**Checkpoint:** send `hello` in the chat and get a normal reply. If you get an authentication error instead, the key is wrong or the provider doesn't match the key. See [failure recovery](#when-something-fails) below. Do not continue until `hello` works.

## Step 3: Have a conversation

Before giving the agent work, send something conversational:

```
What can you actually do?
```

Every message you send wakes the agent for a **run**: it does whatever the message needs, and its reply ends the run. For a question like this, that's the whole story — no actions, no plan, just an answer. The moment your message asks for something actionable, the same run mechanism scales up: actions fire, a plan appears, and the reply arrives when the work is done. There is no command to memorize.

Conversations live in **chat sessions**, listed under **Chats** in the sidebar. **Main** is pinned first, and the **+** button opens a new chat, which titles itself from the first exchange. Each session is independent, so you can keep long-running work in one chat and ask unrelated questions in another. Rename, clear, or delete any session from its menu.

**Checkpoint:** you got a conversational answer, straight away, with no "Working" activity row appearing.

## Step 4: Run your first real task

Ask for something with a concrete deliverable:

```
Research the top 3 Python web frameworks, compare them briefly,
and save the comparison as frameworks.md
```

Watch what happens, in order:

1. **The agent acknowledges and plans.** A request this size gets an immediate one-sentence acknowledgment, a requirements checklist (what the finished output must contain), and a **todo list** the agent checks off live. You'll see phases like collecting information, executing, verifying. Something trivial ("rename this file") skips all of that and just runs. The difference is explained in [Runs](../core/modes/index.md).
2. **A "Working" row ticks.** An always-visible activity row sits in the conversation while the run is in flight. Expand it to watch each step: `web_search` and `web_fetch` calls for research, then `write_file` for the output. Every action the agent takes is visible there, with inputs and results. Nothing happens silently.
3. **The agent may ask you something.** If it needs a decision, the question is its final message and the run pauses there. Just answer in chat — your reply wakes the agent in the same session, with all the context intact, and the work continues.
4. **The final message delivers.** The agent verifies its output against the requirements it recorded, then ends the run with a summary and the artifact path. If something's wrong, say so — your reply starts a new run in the same conversation and it keeps working with full context.

The output lands in the agent's workspace: `agent_file_system/workspace/frameworks.md`. That directory is where run artifacts live. The agent can also send files directly into the chat as attachments. See [Agent file system](../core/concepts/agent-file-system.md).

**Checkpoint:** the agent delivered a final summary, and `frameworks.md` exists in `agent_file_system/workspace/`.

## Step 5: Check logs, agent files, and service status

These three locations are the first places to check when something behaves unexpectedly.

- **Logs.** Every launch writes a folder under `logs/` containing `all.log` (everything, interleaved) plus a `session.log` per session (the main session's folder is `main`). When the agent behaves unexpectedly, this is the ground truth. See [Logs](../core/concepts/logs.md).
- **The agent's files.** `agent_file_system/` is the agent's own home: `USER.md` (what it knows about you), `MEMORY.md` (long-term memory), `SOUL.md` (personality), `EVENT.md` (the full event log), and the `workspace/` you just used. Open `USER.md`. After [onboarding](onboarding.md) it should describe you. See [Agent file system](../core/concepts/agent-file-system.md).
- **Service status.** `python craftbot.py status` tells you whether CraftBot is running and whether auto-start is registered.

**Checkpoint:** you know where logs, memory, and workspace outputs live on disk.

## Step 6: Add capabilities one layer at a time

Everything past this point is optional, and each layer works independently. Add them in this order, and confirm each works before the next:

1. **Connect an integration.** Start with the one you use most: [Telegram](../integrations/telegram-bot.md), [Slack](../integrations/slack.md), [Discord](../integrations/discord.md), or [Gmail](../integrations/gmail.md). Connect from **Settings → Integrations**. Once connected, each integration gets its own command (`/gmail`, `/slack`, ...) and `/cred status` shows what's linked. Now the agent can message you (and be messaged) where you actually are.
2. **Try a skill.** Type `/` in chat to see invokable skills. CraftBot ships with 195, including `/pdf`, day planners, and research workflows. See [Skills](../core/concepts/skills.md).
3. **Schedule something.** "Every weekday at 8am, summarize my unread email and message me on Telegram." Scheduled and recurring tasks are covered in [Scheduling](../core/concepts/scheduling.md).
4. **Turn on proactive mode.** The agent starts planning and proposing work on its own (it always asks before acting). See [Proactive](../core/modes/proactive.md).
5. **Build a Living UI.** Ask for a tool ("build me a habit tracker") and watch it get designed, coded, and launched. See [Living UI](../living-ui/index.md).

## When something fails

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser page never loads | Frontend still building, or Node.js missing | Wait and refresh; check `python craftbot.py logs`; install Node.js LTS or use `--cli` |
| `hello` gets no reply at all | Agent not running, or backend port blocked | `python craftbot.py status`, then `restart`; check ports `7925`/`7926` |
| Authentication / 401 / invalid key error | Wrong key, or key doesn't match selected provider | Re-run `/provider <name> <key>`; verify the key works in the provider's own console |
| Reply is an error about model not found | Provider default model not available on your account | Set an explicit model in **Settings → Model**; see [LLM providers](../core/providers/llm.md) |
| Work starts but hangs on a step | A needed integration or dependency is missing | Expand the "Working" activity row and read the failing action's error; check `logs/` |
| Agent answers but doesn't do the work | The request read as a question, not a job | Phrase the request as a deliverable: what to produce, where to put it |

Deeper diagnosis: [Troubleshooting](../reference/troubleshooting/index.md).

## Quick reference

```bash
python craftbot.py status|start|stop|restart|logs   # manage the background service
python run.py            # run in foreground (browser)
python run.py --cli      # run in foreground (terminal chat)
```

```
/provider [name] [key]   # view or set the model provider
/cred                    # credentials & connected integrations
/skill                   # manage skills          /help    # all commands
/clear                   # clear this session     /tokens  # session token usage
/reset                   # delete all chat sessions and clear history
```

## Next

- [Onboarding](onboarding.md): what the wizard configured, and the interview the agent runs afterwards
- [Your first run](first-task.md): steering, parallel sessions, and how to phrase work
- [Learning path](learning-path.md): pick a reading track for what you want to build
