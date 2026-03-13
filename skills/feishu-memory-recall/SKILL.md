---
name: feishu-memory-recall
version: 2.0.0
description: Cross-group memory, search, and event sharing for OpenClaw Feishu agents
tags: [feishu, memory, cross-session, search, digest]
---

# Feishu Memory Recall

Cross-group awareness for OpenClaw. Search messages, generate digests, and share events across all Feishu groups and DMs.

## Commands

| Command | Description |
|---|---|
| `recall --user <id> [--hours 24]` | Find messages from a user across all groups |
| `search --keyword <text> [--hours 24]` | Search messages by keyword across all groups |
| `digest [--hours 6]` | Activity summary of all tracked groups |
| `log-event -s <source> -e <text>` | Write event to RECENT_EVENTS.md + daily log |
| `sync-groups` | Auto-discover groups from gateway sessions |
| `add-group -i <id> -n <name>` | Manually track a group |
| `list-groups` | Show tracked groups |

## Usage

```bash
# Search for "GIF error" across all groups
node skills/feishu-memory-recall/index.js search -k "GIF" --hours 12

# What happened in all groups in the last 6 hours?
node skills/feishu-memory-recall/index.js digest --hours 6

# Log a cross-session event
node skills/feishu-memory-recall/index.js log-event -s "dev-group" -e "Fixed GIF crash in gateway"

# Auto-discover all Feishu groups from gateway sessions
node skills/feishu-memory-recall/index.js sync-groups

# Find what a specific user said recently
node skills/feishu-memory-recall/index.js recall -u ou_cdc63fe05e88c580aedead04d851fc04 --hours 48
```

## How It Works

1. **sync-groups**: Reads `~/.openclaw/agents/main/sessions/sessions.json` to auto-discover all Feishu groups the agent is connected to.
2. **search/recall/digest**: Calls Feishu API to fetch messages from tracked groups, filters by keyword/user/time.
3. **log-event**: Appends to both `RECENT_EVENTS.md` (rolling 24h cross-session feed) and `memory/YYYY-MM-DD.md` (permanent daily log).

## Configuration

Requires Feishu credentials in `.env`:
```
FEISHU_APP_ID=cli_xxxxx
FEISHU_APP_SECRET=xxxxx
```

Group list is stored in `memory/active_groups.json` and can be auto-populated via `sync-groups`.
