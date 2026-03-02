---
name: trello
description: |
  Trello API integration with managed OAuth. Manage boards, lists, cards, members, and labels. Use this skill when users want to interact with Trello for project management. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
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

# Trello

Access the Trello API with managed OAuth authentication. Manage boards, lists, cards, checklists, labels, and members for project and task management.

## Quick Start

```bash
# Get boards for current user
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/trello/1/members/me/boards')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/trello/{native-api-path}
```

Replace `{native-api-path}` with the actual Trello API endpoint path. The gateway proxies requests to `api.trello.com` and automatically injects your OAuth token.

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

Manage your Trello OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=trello&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'trello'}).encode()
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
    "app": "trello",
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

If you have multiple Trello connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/trello/1/members/me/boards')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Members

#### Get Current Member

```bash
GET /trello/1/members/me
```

#### Get Member's Boards

```bash
GET /trello/1/members/me/boards
```

Query parameters:
- `filter` - Filter boards: `all`, `open`, `closed`, `members`, `organization`, `starred`
- `fields` - Comma-separated fields to include

### Boards

#### Get Board

```bash
GET /trello/1/boards/{id}
```

Query parameters:
- `fields` - Comma-separated fields
- `lists` - Include lists: `all`, `open`, `closed`, `none`
- `cards` - Include cards: `all`, `open`, `closed`, `none`
- `members` - Include members: `all`, `none`

**Example:**

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/trello/1/boards/BOARD_ID?lists=open&cards=open')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

#### Create Board

```bash
POST /trello/1/boards
Content-Type: application/json

{
  "name": "Project Alpha",
  "desc": "Main project board",
  "defaultLists": false,
  "prefs_permissionLevel": "private"
}
```

#### Update Board

```bash
PUT /trello/1/boards/{id}
Content-Type: application/json

{
  "name": "Project Alpha - Updated",
  "desc": "Updated description"
}
```

#### Delete Board

```bash
DELETE /trello/1/boards/{id}
```

#### Get Board Lists

```bash
GET /trello/1/boards/{id}/lists
```

Query parameters:
- `filter` - Filter: `all`, `open`, `closed`, `none`

#### Get Board Cards

```bash
GET /trello/1/boards/{id}/cards
```

#### Get Board Members

```bash
GET /trello/1/boards/{id}/members
```

### Lists

#### Get List

```bash
GET /trello/1/lists/{id}
```

#### Create List

```bash
POST /trello/1/lists
Content-Type: application/json

{
  "name": "To Do",
  "idBoard": "BOARD_ID",
  "pos": "top"
}
```

#### Update List

```bash
PUT /trello/1/lists/{id}
Content-Type: application/json

{
  "name": "In Progress"
}
```

#### Archive List

```bash
PUT /trello/1/lists/{id}/closed
Content-Type: application/json

{
  "value": true
}
```

#### Get Cards in List

```bash
GET /trello/1/lists/{id}/cards
```

#### Move All Cards in List

```bash
POST /trello/1/lists/{id}/moveAllCards
Content-Type: application/json

{
  "idBoard": "BOARD_ID",
  "idList": "TARGET_LIST_ID"
}
```

### Cards

#### Get Card

```bash
GET /trello/1/cards/{id}
```

Query parameters:
- `fields` - Comma-separated fields
- `members` - Include members (true/false)
- `checklists` - Include checklists: `all`, `none`
- `attachments` - Include attachments (true/false)

#### Create Card

```bash
POST /trello/1/cards
Content-Type: application/json

{
  "name": "Implement feature X",
  "desc": "Description of the task",
  "idList": "LIST_ID",
  "pos": "bottom",
  "due": "2025-03-30T12:00:00.000Z",
  "idMembers": ["MEMBER_ID"],
  "idLabels": ["LABEL_ID"]
}
```

#### Update Card

```bash
PUT /trello/1/cards/{id}
Content-Type: application/json

{
  "name": "Updated card name",
  "desc": "Updated description",
  "due": "2025-04-15T12:00:00.000Z",
  "dueComplete": false
}
```

#### Move Card to List

```bash
PUT /trello/1/cards/{id}
Content-Type: application/json

{
  "idList": "NEW_LIST_ID",
  "pos": "top"
}
```

#### Delete Card

```bash
DELETE /trello/1/cards/{id}
```

#### Add Comment to Card

```bash
POST /trello/1/cards/{id}/actions/comments
Content-Type: application/json

{
  "text": "This is a comment"
}
```

#### Add Member to Card

```bash
POST /trello/1/cards/{id}/idMembers
Content-Type: application/json

{
  "value": "MEMBER_ID"
}
```

#### Remove Member from Card

```bash
DELETE /trello/1/cards/{id}/idMembers/{idMember}
```

#### Add Label to Card

```bash
POST /trello/1/cards/{id}/idLabels
Content-Type: application/json

{
  "value": "LABEL_ID"
}
```

### Checklists

#### Get Checklist

```bash
GET /trello/1/checklists/{id}
```

#### Create Checklist

```bash
POST /trello/1/checklists
Content-Type: application/json

{
  "idCard": "CARD_ID",
  "name": "Task Checklist"
}
```

#### Create Checklist Item

```bash
POST /trello/1/checklists/{id}/checkItems
Content-Type: application/json

{
  "name": "Subtask 1",
  "pos": "bottom",
  "checked": false
}
```

#### Update Checklist Item

```bash
PUT /trello/1/cards/{cardId}/checkItem/{checkItemId}
Content-Type: application/json

{
  "state": "complete"
}
```

#### Delete Checklist

```bash
DELETE /trello/1/checklists/{id}
```

### Labels

#### Get Board Labels

```bash
GET /trello/1/boards/{id}/labels
```

#### Create Label

```bash
POST /trello/1/labels
Content-Type: application/json

{
  "name": "High Priority",
  "color": "red",
  "idBoard": "BOARD_ID"
}
```

Colors: `yellow`, `purple`, `blue`, `red`, `green`, `orange`, `black`, `sky`, `pink`, `lime`, `null` (no color)

#### Update Label

```bash
PUT /trello/1/labels/{id}
Content-Type: application/json

{
  "name": "Critical",
  "color": "red"
}
```

#### Delete Label

```bash
DELETE /trello/1/labels/{id}
```

### Search

#### Search All

```bash
GET /trello/1/search?query=keyword&modelTypes=cards,boards
```

Query parameters:
- `query` - Search query (required)
- `modelTypes` - Comma-separated: `actions`, `boards`, `cards`, `members`, `organizations`
- `board_fields` - Fields to return for boards
- `card_fields` - Fields to return for cards
- `cards_limit` - Max cards to return (1-1000)

## Code Examples

### JavaScript

```javascript
const headers = {
  'Authorization': `Bearer ${process.env.MATON_API_KEY}`
};

// Get boards
const boards = await fetch(
  'https://gateway.maton.ai/trello/1/members/me/boards',
  { headers }
).then(r => r.json());

// Create card
await fetch(
  'https://gateway.maton.ai/trello/1/cards',
  {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'New Task',
      idList: 'LIST_ID',
      desc: 'Task description'
    })
  }
);
```

### Python

```python
import os
import requests

headers = {'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'}

# Get boards
boards = requests.get(
    'https://gateway.maton.ai/trello/1/members/me/boards',
    headers=headers
).json()

# Create card
response = requests.post(
    'https://gateway.maton.ai/trello/1/cards',
    headers=headers,
    json={
        'name': 'New Task',
        'idList': 'LIST_ID',
        'desc': 'Task description'
    }
)
```

## Notes

- IDs are 24-character alphanumeric strings
- Use `me` to reference the authenticated user
- Dates are in ISO 8601 format
- `pos` can be `top`, `bottom`, or a positive number
- Card positions within lists are floating point numbers
- Use `fields` parameter to limit returned data and improve performance
- Archived items can be retrieved with `filter=closed`
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets (`fields[]`, `sort[]`, `records[]`) to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing Trello connection or invalid request |
| 401 | Invalid or missing Maton API key |
| 404 | Board, list, or card not found |
| 429 | Rate limited (10 req/sec per account) |
| 4xx/5xx | Passthrough error from Trello API |

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

1. Ensure your URL path starts with `trello`. For example:

- Correct: `https://gateway.maton.ai/trello/1/members/me/boards`
- Incorrect: `https://gateway.maton.ai/1/members/me/boards`

## Resources

- [Trello API Overview](https://developer.atlassian.com/cloud/trello/rest/api-group-actions/)
- [Boards](https://developer.atlassian.com/cloud/trello/rest/api-group-boards/)
- [Lists](https://developer.atlassian.com/cloud/trello/rest/api-group-lists/)
- [Cards](https://developer.atlassian.com/cloud/trello/rest/api-group-cards/)
- [Checklists](https://developer.atlassian.com/cloud/trello/rest/api-group-checklists/)
- [Labels](https://developer.atlassian.com/cloud/trello/rest/api-group-labels/)
- [Members](https://developer.atlassian.com/cloud/trello/rest/api-group-members/)
- [Search](https://developer.atlassian.com/cloud/trello/rest/api-group-search/)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
