---
name: pipedrive
description: |
  Pipedrive API integration with managed OAuth. Manage deals, persons, organizations, activities, and pipelines. Use this skill when users want to interact with Pipedrive CRM. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
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

# Pipedrive

Access the Pipedrive API with managed OAuth authentication. Manage deals, persons, organizations, activities, pipelines, and more for sales CRM workflows.

## Quick Start

```bash
# List deals
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/pipedrive/api/v1/deals')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/pipedrive/{native-api-path}
```

Replace `{native-api-path}` with the actual Pipedrive API endpoint path. The gateway proxies requests to `api.pipedrive.com` and automatically injects your OAuth token.

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

Manage your Pipedrive OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=pipedrive&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'pipedrive'}).encode()
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
    "app": "pipedrive",
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

If you have multiple Pipedrive connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/pipedrive/api/v1/deals')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Deals

#### List Deals

```bash
GET /pipedrive/api/v1/deals
```

Query parameters:
- `status` - Filter by status: `open`, `won`, `lost`, `deleted`, `all_not_deleted`
- `filter_id` - Filter ID to use
- `stage_id` - Filter by stage
- `user_id` - Filter by user
- `start` - Pagination start (default 0)
- `limit` - Items per page (default 100)
- `sort` - Sort field and order (e.g., `add_time DESC`)

**Example:**

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/pipedrive/api/v1/deals?status=open&limit=50')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

#### Get Deal

```bash
GET /pipedrive/api/v1/deals/{id}
```

#### Create Deal

```bash
POST /pipedrive/api/v1/deals
Content-Type: application/json

{
  "title": "New Enterprise Deal",
  "value": 50000,
  "currency": "USD",
  "person_id": 123,
  "org_id": 456,
  "stage_id": 1,
  "expected_close_date": "2025-06-30"
}
```

#### Update Deal

```bash
PUT /pipedrive/api/v1/deals/{id}
Content-Type: application/json

{
  "title": "Updated Deal Title",
  "value": 75000,
  "status": "won"
}
```

#### Delete Deal

```bash
DELETE /pipedrive/api/v1/deals/{id}
```

#### Search Deals

```bash
GET /pipedrive/api/v1/deals/search?term=enterprise
```

### Persons (Contacts)

#### List Persons

```bash
GET /pipedrive/api/v1/persons
```

Query parameters:
- `filter_id` - Filter ID
- `start` - Pagination start
- `limit` - Items per page
- `sort` - Sort field and order

#### Get Person

```bash
GET /pipedrive/api/v1/persons/{id}
```

#### Create Person

```bash
POST /pipedrive/api/v1/persons
Content-Type: application/json

{
  "name": "John Doe",
  "email": ["john@example.com"],
  "phone": ["+1234567890"],
  "org_id": 456,
  "visible_to": 3
}
```

#### Update Person

```bash
PUT /pipedrive/api/v1/persons/{id}
Content-Type: application/json

{
  "name": "John Smith",
  "email": ["john.smith@example.com"]
}
```

#### Delete Person

```bash
DELETE /pipedrive/api/v1/persons/{id}
```

#### Search Persons

```bash
GET /pipedrive/api/v1/persons/search?term=john
```

### Organizations

#### List Organizations

```bash
GET /pipedrive/api/v1/organizations
```

#### Get Organization

```bash
GET /pipedrive/api/v1/organizations/{id}
```

#### Create Organization

```bash
POST /pipedrive/api/v1/organizations
Content-Type: application/json

{
  "name": "Acme Corporation",
  "address": "123 Main St, City, Country",
  "visible_to": 3
}
```

#### Update Organization

```bash
PUT /pipedrive/api/v1/organizations/{id}
Content-Type: application/json

{
  "name": "Acme Corp International"
}
```

#### Delete Organization

```bash
DELETE /pipedrive/api/v1/organizations/{id}
```

### Activities

#### List Activities

```bash
GET /pipedrive/api/v1/activities
```

Query parameters:
- `type` - Activity type (e.g., `call`, `meeting`, `task`, `email`)
- `done` - Filter by completion (0 or 1)
- `user_id` - Filter by user
- `start_date` - Filter by start date
- `end_date` - Filter by end date

#### Get Activity

```bash
GET /pipedrive/api/v1/activities/{id}
```

#### Create Activity

```bash
POST /pipedrive/api/v1/activities
Content-Type: application/json

{
  "subject": "Follow-up call",
  "type": "call",
  "due_date": "2025-03-15",
  "due_time": "14:00",
  "duration": "00:30",
  "deal_id": 789,
  "person_id": 123,
  "note": "Discuss contract terms"
}
```

#### Update Activity

```bash
PUT /pipedrive/api/v1/activities/{id}
Content-Type: application/json

{
  "done": 1,
  "note": "Completed - customer agreed to terms"
}
```

#### Delete Activity

```bash
DELETE /pipedrive/api/v1/activities/{id}
```

### Pipelines

#### List Pipelines

```bash
GET /pipedrive/api/v1/pipelines
```

#### Get Pipeline

```bash
GET /pipedrive/api/v1/pipelines/{id}
```

### Stages

#### List Stages

```bash
GET /pipedrive/api/v1/stages
```

Query parameters:
- `pipeline_id` - Filter by pipeline

#### Get Stage

```bash
GET /pipedrive/api/v1/stages/{id}
```

### Notes

#### List Notes

```bash
GET /pipedrive/api/v1/notes
```

Query parameters:
- `deal_id` - Filter by deal
- `person_id` - Filter by person
- `org_id` - Filter by organization

#### Create Note

```bash
POST /pipedrive/api/v1/notes
Content-Type: application/json

{
  "content": "Meeting notes: Discussed pricing and timeline",
  "deal_id": 789,
  "pinned_to_deal_flag": 1
}
```

### Users

#### List Users

```bash
GET /pipedrive/api/v1/users
```

#### Get Current User

```bash
GET /pipedrive/api/v1/users/me
```

## Code Examples

### JavaScript

```javascript
const headers = {
  'Authorization': `Bearer ${process.env.MATON_API_KEY}`
};

// List open deals
const deals = await fetch(
  'https://gateway.maton.ai/pipedrive/api/v1/deals?status=open',
  { headers }
).then(r => r.json());

// Create a deal
await fetch(
  'https://gateway.maton.ai/pipedrive/api/v1/deals',
  {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: 'New Deal',
      value: 10000,
      currency: 'USD'
    })
  }
);
```

### Python

```python
import os
import requests

headers = {'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'}

# List open deals
deals = requests.get(
    'https://gateway.maton.ai/pipedrive/api/v1/deals',
    headers=headers,
    params={'status': 'open'}
).json()

# Create a deal
response = requests.post(
    'https://gateway.maton.ai/pipedrive/api/v1/deals',
    headers=headers,
    json={
        'title': 'New Deal',
        'value': 10000,
        'currency': 'USD'
    }
)
```

## Notes

- IDs are integers
- Email and phone fields accept arrays for multiple values
- `visible_to` values: 1 (owner only), 3 (entire company), 5 (owner's visibility group), 7 (entire company and visibility group)
- Deal status: `open`, `won`, `lost`, `deleted`
- Use `start` and `limit` for pagination
- Custom fields are supported via their API key (e.g., `abc123_custom_field`)
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets (`fields[]`, `sort[]`, `records[]`) to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing Pipedrive connection |
| 401 | Invalid or missing Maton API key |
| 404 | Resource not found |
| 429 | Rate limited (10 req/sec per account) |
| 4xx/5xx | Passthrough error from Pipedrive API |

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

1. Ensure your URL path starts with `pipedrive`. For example:

- Correct: `https://gateway.maton.ai/pipedrive/api/v1/deals`
- Incorrect: `https://gateway.maton.ai/api/v1/deals`

## Resources

- [Pipedrive API Overview](https://developers.pipedrive.com/docs/api/v1)
- [Deals](https://developers.pipedrive.com/docs/api/v1/Deals)
- [Persons](https://developers.pipedrive.com/docs/api/v1/Persons)
- [Organizations](https://developers.pipedrive.com/docs/api/v1/Organizations)
- [Activities](https://developers.pipedrive.com/docs/api/v1/Activities)
- [Pipelines](https://developers.pipedrive.com/docs/api/v1/Pipelines)
- [Stages](https://developers.pipedrive.com/docs/api/v1/Stages)
- [Notes](https://developers.pipedrive.com/docs/api/v1/Notes)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
