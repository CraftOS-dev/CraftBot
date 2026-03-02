---
name: whatsapp-business
description: |
  WhatsApp Business API integration with managed OAuth. Send messages, manage templates, and handle conversations. Use this skill when users want to interact with WhatsApp Business. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
compatibility: Requires network access and valid Maton API key
metadata:
  author: maton
  version: "1.0"
  clawdbot:
    emoji: 🧠
    requires:
      env:
        - MATON_API_KEY
---

# WhatsApp Business

Access the WhatsApp Business API with managed OAuth authentication. Send messages, manage message templates, handle media, and interact with customers through WhatsApp.

## Quick Start

```bash
# Send a text message
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'messaging_product': 'whatsapp', 'to': '1234567890', 'type': 'text', 'text': {'body': 'Hello from WhatsApp Business!'}}).encode()
req = urllib.request.Request('https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Content-Type', 'application/json')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/whatsapp-business/{native-api-path}
```

Replace `{native-api-path}` with the actual WhatsApp Business API endpoint path. The gateway proxies requests to `graph.facebook.com` and automatically injects your OAuth token.

## Authentication

All requests require the Maton API key in the Authorization header:

```
Authorization: Bearer $MATON_API_KEY
```

**Environment Variable:** Set your API key as `MATON_API_KEY`:

```bash
export MATON_API_KEY="YOUR_API_KEY"
```

### Getting Your API Key

1. Sign in or create an account at [maton.ai](https://maton.ai)
2. Go to [maton.ai/settings](https://maton.ai/settings)
3. Copy your API key

## Connection Management

Manage your WhatsApp Business OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=whatsapp-business&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'whatsapp-business'}).encode()
req = urllib.request.Request('https://ctrl.maton.ai/connections', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Content-Type', 'application/json')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Get Connection

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections/{connection_id}')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

**Response:**
```json
{
  "connection": {
    "connection_id": "21fd90f9-5935-43cd-b6c8-bde9d915ca80",
    "status": "ACTIVE",
    "creation_time": "2025-12-08T07:20:53.488460Z",
    "last_updated_time": "2026-01-31T20:03:32.593153Z",
    "url": "https://connect.maton.ai/?session_token=...",
    "app": "whatsapp-business",
    "metadata": {}
  }
}
```

Open the returned `url` in a browser to complete OAuth authorization.

### Delete Connection

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections/{connection_id}', method='DELETE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Specifying Connection

If you have multiple WhatsApp Business connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'messaging_product': 'whatsapp', 'to': '1234567890', 'type': 'text', 'text': {'body': 'Hello!'}}).encode()
req = urllib.request.Request('https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
req.add_header('Content-Type', 'application/json')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Messages

#### Send Text Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "1234567890",
  "type": "text",
  "text": {
    "preview_url": true,
    "body": "Hello! Check out https://example.com"
  }
}
```

#### Send Template Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "template",
  "template": {
    "name": "hello_world",
    "language": {
      "code": "en_US"
    },
    "components": [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "John"}
        ]
      }
    ]
  }
}
```

#### Send Image Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "image",
  "image": {
    "link": "https://example.com/image.jpg",
    "caption": "Check out this image!"
  }
}
```

#### Send Document Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "document",
  "document": {
    "link": "https://example.com/document.pdf",
    "caption": "Here's the document",
    "filename": "report.pdf"
  }
}
```

#### Send Video Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "video",
  "video": {
    "link": "https://example.com/video.mp4",
    "caption": "Watch this video"
  }
}
```

#### Send Audio Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "audio",
  "audio": {
    "link": "https://example.com/audio.mp3"
  }
}
```

#### Send Location Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "location",
  "location": {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "name": "San Francisco",
    "address": "San Francisco, CA, USA"
  }
}
```

#### Send Contact Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "contacts",
  "contacts": [
    {
      "name": {
        "formatted_name": "John Doe",
        "first_name": "John",
        "last_name": "Doe"
      },
      "phones": [
        {"phone": "+1234567890", "type": "MOBILE"}
      ]
    }
  ]
}
```

#### Send Interactive Button Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "interactive",
  "interactive": {
    "type": "button",
    "body": {
      "text": "Would you like to proceed?"
    },
    "action": {
      "buttons": [
        {"type": "reply", "reply": {"id": "yes", "title": "Yes"}},
        {"type": "reply", "reply": {"id": "no", "title": "No"}}
      ]
    }
  }
}
```

#### Send Interactive List Message

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "1234567890",
  "type": "interactive",
  "interactive": {
    "type": "list",
    "header": {"type": "text", "text": "Select an option"},
    "body": {"text": "Choose from the list below"},
    "action": {
      "button": "View Options",
      "sections": [
        {
          "title": "Products",
          "rows": [
            {"id": "prod1", "title": "Product 1", "description": "First product"},
            {"id": "prod2", "title": "Product 2", "description": "Second product"}
          ]
        }
      ]
    }
  }
}
```

#### Mark Message as Read

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/messages
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "status": "read",
  "message_id": "wamid.xxxxx"
}
```

### Media

#### Upload Media

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/media
Content-Type: multipart/form-data

file=@/path/to/file.jpg
type=image/jpeg
messaging_product=whatsapp
```

#### Get Media URL

```bash
GET /whatsapp-business/v21.0/{media_id}
```

#### Delete Media

```bash
DELETE /whatsapp-business/v21.0/{media_id}
```

### Message Templates

#### List Templates

```bash
GET /whatsapp-business/v21.0/{whatsapp_business_account_id}/message_templates
```

Query parameters:
- `limit` - Number of templates to return
- `status` - Filter by status: `APPROVED`, `PENDING`, `REJECTED`

#### Create Template

```bash
POST /whatsapp-business/v21.0/{whatsapp_business_account_id}/message_templates
Content-Type: application/json

{
  "name": "order_confirmation",
  "language": "en_US",
  "category": "UTILITY",
  "components": [
    {
      "type": "HEADER",
      "format": "TEXT",
      "text": "Order Confirmation"
    },
    {
      "type": "BODY",
      "text": "Hi {{1}}, your order #{{2}} has been confirmed!"
    },
    {
      "type": "FOOTER",
      "text": "Thank you for your purchase"
    }
  ]
}
```

Template categories: `AUTHENTICATION`, `MARKETING`, `UTILITY`

#### Delete Template

```bash
DELETE /whatsapp-business/v21.0/{whatsapp_business_account_id}/message_templates?name=template_name
```

### Phone Numbers

#### Get Phone Number

```bash
GET /whatsapp-business/v21.0/{phone_number_id}
```

#### List Phone Numbers

```bash
GET /whatsapp-business/v21.0/{whatsapp_business_account_id}/phone_numbers
```

### Business Profile

#### Get Business Profile

```bash
GET /whatsapp-business/v21.0/{phone_number_id}/whatsapp_business_profile?fields=about,address,description,email,profile_picture_url,websites,vertical
```

#### Update Business Profile

```bash
POST /whatsapp-business/v21.0/{phone_number_id}/whatsapp_business_profile
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "about": "Your trusted partner",
  "address": "123 Business St",
  "description": "We provide excellent services",
  "email": "contact@example.com",
  "websites": ["https://example.com"],
  "vertical": "RETAIL"
}
```

## Code Examples

### JavaScript

```javascript
const headers = {
  'Authorization': `Bearer ${process.env.MATON_API_KEY}`,
  'Content-Type': 'application/json'
};

// Send text message
await fetch(
  'https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages',
  {
    method: 'POST',
    headers,
    body: JSON.stringify({
      messaging_product: 'whatsapp',
      to: '1234567890',
      type: 'text',
      text: { body: 'Hello from WhatsApp!' }
    })
  }
);

// Send template message
await fetch(
  'https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages',
  {
    method: 'POST',
    headers,
    body: JSON.stringify({
      messaging_product: 'whatsapp',
      to: '1234567890',
      type: 'template',
      template: {
        name: 'hello_world',
        language: { code: 'en_US' }
      }
    })
  }
);
```

### Python

```python
import os
import requests

headers = {
    'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}',
    'Content-Type': 'application/json'
}

# Send text message
response = requests.post(
    'https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages',
    headers=headers,
    json={
        'messaging_product': 'whatsapp',
        'to': '1234567890',
        'type': 'text',
        'text': {'body': 'Hello from WhatsApp!'}
    }
)

# Send template message
response = requests.post(
    'https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages',
    headers=headers,
    json={
        'messaging_product': 'whatsapp',
        'to': '1234567890',
        'type': 'template',
        'template': {
            'name': 'hello_world',
            'language': {'code': 'en_US'}
        }
    }
)
```

## Notes

- Phone numbers must be in international format without `+` or leading zeros (e.g., `1234567890`)
- `messaging_product` must always be set to `whatsapp`
- Template messages are required for initiating conversations (24-hour messaging window)
- Media files must be publicly accessible URLs or uploaded via the Media API
- Interactive messages support up to 3 buttons or 10 list items
- Message IDs (`wamid`) are used to track message status and replies
- API version `v21.0` is current; check Meta docs for latest version
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets (`fields[]`, `sort[]`, `records[]`) to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing WhatsApp Business connection or invalid request |
| 401 | Invalid or missing Maton API key |
| 404 | Phone number or resource not found |
| 429 | Rate limited (10 req/sec per account) |
| 4xx/5xx | Passthrough error from WhatsApp Business API |

Common error codes from WhatsApp:
- `131030` - Phone number not registered
- `131031` - Message failed to send
- `132000` - Template not found or not approved
- `133010` - Phone number rate limit reached

### Troubleshooting: API Key Issues

1. Check that the `MATON_API_KEY` environment variable is set:

```bash
echo $MATON_API_KEY
```

2. Verify the API key is valid by listing connections:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Troubleshooting: Invalid App Name

1. Ensure your URL path starts with `whatsapp-business`. For example:

- Correct: `https://gateway.maton.ai/whatsapp-business/v21.0/PHONE_NUMBER_ID/messages`
- Incorrect: `https://gateway.maton.ai/v21.0/PHONE_NUMBER_ID/messages`

## Resources

- [WhatsApp Business API Overview](https://developers.facebook.com/docs/whatsapp/cloud-api/overview)
- [Send Messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages)
- [Message Templates](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates)
- [Media](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media)
- [Phone Numbers](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/phone-numbers)
- [Business Profiles](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/business-profiles)
- [Webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks)
- [Error Codes](https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
