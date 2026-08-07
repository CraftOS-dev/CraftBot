# WhatsApp Business

The WhatsApp Business integration connects CraftBot to Meta's WhatsApp Business Platform (the Cloud API) with an access token and a phone number ID. It sends messages from your business number and receives inbound messages through a Meta webhook. This route suits production messaging with higher limits. It does not expose a set of dedicated agent actions. If you want the agent to drive WhatsApp directly with per-message tools, use [WhatsApp Web](whatsapp-web.md) instead, and read [How it connects](#how-it-connects) below for why.

## Requirements

| Requirement | Details |
|---|---|
| Meta developer account | Create one at [developers.facebook.com](https://developers.facebook.com/) |
| Business-type app with WhatsApp | Add the **WhatsApp** product to the app |
| Access token | A temporary token from **API Setup**, or a permanent System User token for production |
| Phone number ID | The numeric `phone_number_id` shown under the "From" number on API Setup (not a phone number) |
| Recipient opt-in | The recipient must have messaged your business number, or you send an approved template |
| Webhook (for inbound) | Configured in the Meta dashboard and pointed at your CraftBot instance |

## Setup

1. Open [developers.facebook.com/apps](https://developers.facebook.com/apps) and create an app of type **Business**.
2. Add the **WhatsApp** product to the app.
3. On the **WhatsApp → API Setup** tab, copy the temporary access token, or generate a permanent one under **System Users** for production.
4. On the same page, copy the **Phone Number ID** shown under the "From" phone number.
5. Add a recipient phone number for testing on the same page.
6. In CraftBot, open **Settings → Integrations → WhatsApp Business**, paste the access token and phone number ID, and connect. From chat, `/whatsapp-business login <access_token> <phone_number_id>` does the same thing.
7. Verify with `/whatsapp-business status`. It shows the connected phone number ID.

`/whatsapp-business logout` removes the credential.

## How it connects

**Authentication.** Every call sends the access token as a bearer token to the Meta Graph API. At login CraftBot validates the token and phone number ID against the Graph API, then stores both in the credential store as `whatsapp_business.json`. The phone number ID is the sending identity, so the agent never asks you for "your WhatsApp number". See [Credentials](credentials.md).

**Sending and receiving.** CraftBot connects this integration as a messaging platform. It sends outbound text, template, image, and document messages through the Cloud API, and it can mark inbound messages as read and fetch media a sender attached. Recipients are bare phone numbers in E.164 form without a plus sign or formatting.

**No polling listener.** The Cloud API does not push messages by long-poll. Inbound messages arrive only if you configure a webhook in the Meta dashboard and point it at your CraftBot instance. Without that webhook, this integration is outbound only.

**No dedicated agent actions.** This integration does not register per-message action tools. The agent-facing WhatsApp actions (reply, send media, read chats, manage groups, and so on) all belong to [WhatsApp Web](whatsapp-web.md). Connect WhatsApp Business when you need a production number and Meta compliance; connect WhatsApp Web when you want the agent to operate WhatsApp with the full action surface.

## What the agent can do

WhatsApp Business exposes platform-level messaging rather than a catalog of agent actions. Through the messaging facade, CraftBot supports the following.

| Capability | Purpose |
|---|---|
| Send text | Send a free-form text message inside the 24-hour customer-service window |
| Send template | Send a pre-approved template message, required to reach a recipient outside the 24-hour window |
| Send image | Send an image by public HTTPS URL with an optional caption |
| Send document | Send a document by public HTTPS URL with an optional filename and caption |
| Mark as read | Mark an inbound message as read |
| Fetch media URL | Resolve the download URL and type for media a sender attached |
| Read business profile | Read the connected number's business profile fields |

For interactive control, group management, contact lookup, and message editing, use the [WhatsApp Web](whatsapp-web.md) actions.

## Example requests

```
Send a WhatsApp Business message to 14155552671 saying their order shipped.
```

```
Send the order_confirmation template in en_US to 14155552671.
```

```
Send this image URL to 14155552671 with the caption "Your receipt".
```

```
Mark the last inbound WhatsApp Business message as read.
```

## Configuration

WhatsApp Business has no persistent configuration knobs. Two Meta rules govern sending.

| Rule | Effect |
|---|---|
| 24-hour window | Free-form text only reaches a recipient who messaged you in the last 24 hours. Outside that window, send an approved template instead |
| Approved templates | A template must already exist and be approved in your Meta Business account, with its name, language code, and placeholder components; CraftBot cannot create templates |

To receive inbound messages, configure a webhook in the Meta dashboard and point it at your CraftBot instance. Inbound delivery depends entirely on that webhook.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Token expired" or 401 | The temporary access token lasted about 23 hours and expired | Generate a permanent System User token and run `/whatsapp-business login <token> <phone_number_id>` |
| "Invalid credentials" at login | The access token or phone number ID is wrong | Recopy both from the **API Setup** tab; the phone number ID is a numeric ID, not the phone number |
| Free-form text is rejected | You are outside the 24-hour customer-service window | Send an approved template with `send_template` instead |
| Recipient never receives a message | The recipient has not opted in, or the template category is wrong | Have them message your number first, or use an approved template in the right category |
| No inbound messages reach the agent | No webhook is configured | Set up a webhook in the Meta dashboard and point it at your CraftBot instance |
| You need reply, groups, or contact actions | Those are not part of this integration | Connect [WhatsApp Web](whatsapp-web.md) for full agent control |

## Next

- [WhatsApp Web](whatsapp-web.md): the QR-linked route with the full WhatsApp action surface
- [Credentials](credentials.md): where the token is stored and how `/cred status` reports it
- [Triggers](../core/concepts/triggers.md): how inbound messages become tasks
