# External Integrations (Google, Discord, Slack, etc.)

CraftBot has connected external services (Gmail, YouTube, Discord, Slack, Notion, etc.).
Living UIs can access these through a built-in integration bridge — **do NOT build OAuth flows, API key management, or credential storage yourself.**

The template includes `backend/services/integration_client.py`. Use it:

```python
from services.integration_client import integration

# Check what integrations are connected
integrations = await integration.get_integrations()
# [{"id": "google_workspace", "connected": true}, {"id": "slack", "connected": true}, ...]

# Make an authenticated API call (CraftBot injects credentials automatically)
result = await integration.request(
    integration="google_workspace",
    method="GET",
    url="https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
)
if result.get("status") == 200:
    channels = result["data"]
```

## Available Integrations

google_workspace (Gmail, Calendar, Drive, YouTube), slack, discord, notion, telegram, github, jira, linkedin, twitter, outlook, whatsapp

## Rules

- NEVER implement OAuth or credential management — the bridge handles all auth
- NEVER ask users for API keys — CraftBot already has their connected accounts
- NEVER store tokens or secrets in the Living UI code or database
- Use `integration.available` to check if the bridge is connected before making calls
- Show a helpful message if an integration is not connected (e.g., "Connect Google in CraftBot settings")

## In-App AI (CraftBot's LLM/VLM — no API keys)

```python
from services.integration_client import integration

# Text: summarize / classify / extract / draft
summary = await integration.llm(
    "Summarize these tasks in 3 bullets:\n" + tasks_text,
    system_message="You are a concise assistant.",   # optional
)

# Vision: describe an uploaded image
description = await integration.describe_image(image_url)
```

Returns `""` on failure (bridge down / standalone run) — always handle
the empty case in the UI ("AI unavailable"). Calls take seconds: run them
in custom routes the frontend awaits with a loading state, never in loops
over many rows without telling the user.

## Notification Recipes (send email / Slack / Discord)

Wire these as custom routes + ops (great with `"schedule"`):

**Gmail** (integration `google_workspace`):

```python
import base64
from email.mime.text import MIMEText

def _gmail_raw(to: str, subject: str, body: str) -> str:
    msg = MIMEText(body)
    msg["to"], msg["subject"] = to, subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()

result = await integration.request(
    integration="google_workspace",
    method="POST",
    url="https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    body={"raw": _gmail_raw("me@example.com", "Daily digest", digest_text)},
)
```

**Slack** (integration `slack` — channel ID, not name):

```python
result = await integration.request(
    integration="slack",
    method="POST",
    url="https://slack.com/api/chat.postMessage",
    body={"channel": "C0123456789", "text": digest_text},
)
```

**Discord** (integration `discord` — 18-digit channel ID):

```python
result = await integration.request(
    integration="discord",
    method="POST",
    url="https://discord.com/api/v10/channels/<channel_id>/messages",
    body={"content": digest_text},
)
```

Always check `result.get("status")` — 424 means the user hasn't connected
that service in CraftBot (show "Connect <service> in CraftBot settings").

