---
name: attio
description: |
  Attio API integration with managed OAuth. Manage CRM data including people, companies, and custom objects.
  Use this skill when users want to create, read, update, or delete records in Attio, manage tasks, notes, comments, lists, meetings, or query CRM data.
  For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
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

# Attio

Access the Attio REST API with managed OAuth authentication. Manage CRM objects, records, tasks, notes, comments, lists, list entries, meetings, call recordings, and workspace data.

## Quick Start

```bash
# List all objects in workspace
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/attio/v2/objects')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/attio/{native-api-path}
```

Replace `{native-api-path}` with the actual Attio API endpoint path. The gateway proxies requests to `api.attio.com` and automatically injects your OAuth token.

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

Manage your Attio OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=attio&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'attio'}).encode()
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
    "connection_id": "67b77f19-206e-494c-82c2-8668396fc1f1",
    "status": "ACTIVE",
    "creation_time": "2026-02-06T03:13:17.061608Z",
    "last_updated_time": "2026-02-06T03:13:17.061617Z",
    "url": "https://connect.maton.ai/?session_token=...",
    "app": "attio",
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

If you have multiple Attio connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/attio/v2/objects')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '67b77f19-206e-494c-82c2-8668396fc1f1')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Objects

Objects are the schema definitions (like People, Companies, or custom objects).

#### List Objects

```bash
GET /attio/v2/objects
```

Returns all system-defined and custom objects in your workspace.

#### Get Object

```bash
GET /attio/v2/objects/{object}
```

Get a specific object by slug (e.g., `people`, `companies`) or UUID.

### Attributes

Attributes define the fields on objects.

#### List Attributes

```bash
GET /attio/v2/objects/{object}/attributes
```

Returns all attributes for an object.

### Records

Records are the actual data entries (people, companies, etc.).

#### Query Records

```bash
POST /attio/v2/objects/{object}/records/query
Content-Type: application/json

{
  "limit": 50,
  "offset": 0,
  "filter": {},
  "sorts": []
}
```

Query parameters in body:
- `limit`: Maximum results (default 500)
- `offset`: Number of results to skip
- `filter`: Filter criteria object
- `sorts`: Array of sort specifications

#### Get Record

```bash
GET /attio/v2/objects/{object}/records/{record_id}
```

#### Create Record

```bash
POST /attio/v2/objects/{object}/records
Content-Type: application/json

{
  "data": {
    "values": {
      "name": [{"first_name": "John", "last_name": "Doe", "full_name": "John Doe"}],
      "email_addresses": ["john@example.com"]
    }
  }
}
```

Note: For `personal-name` type attributes (like `name` on people), you must include `full_name` along with `first_name` and `last_name`.

#### Update Record

```bash
PATCH /attio/v2/objects/{object}/records/{record_id}
Content-Type: application/json

{
  "data": {
    "values": {
      "job_title": "Software Engineer"
    }
  }
}
```

#### Delete Record

```bash
DELETE /attio/v2/objects/{object}/records/{record_id}
```

### Tasks

#### List Tasks

```bash
GET /attio/v2/tasks?limit=50
```

Query parameters:
- `limit`: Maximum results (default 500)
- `offset`: Number to skip
- `sort`: `created_at:asc` or `created_at:desc`
- `linked_object`: Filter by object type (e.g., `people`)
- `linked_record_id`: Filter by specific record
- `assignee`: Filter by assignee email/ID
- `is_completed`: Filter by completion status (true/false)

#### Get Task

```bash
GET /attio/v2/tasks/{task_id}
```

#### Create Task

```bash
POST /attio/v2/tasks
Content-Type: application/json

{
  "data": {
    "content": "Follow up with customer",
    "format": "plaintext",
    "deadline_at": "2026-02-15T00:00:00.000000000Z",
    "is_completed": false,
    "assignees": [],
    "linked_records": [
      {
        "target_object": "companies",
        "target_record_id": "16f2fc57-5d22-48b8-b9db-8b0e6d99e9bc"
      }
    ]
  }
}
```

Required fields: `content`, `format`, `deadline_at`, `assignees`, `linked_records`

#### Update Task

```bash
PATCH /attio/v2/tasks/{task_id}
Content-Type: application/json

{
  "data": {
    "is_completed": true
  }
}
```

#### Delete Task

```bash
DELETE /attio/v2/tasks/{task_id}
```

### Workspace Members

#### List Workspace Members

```bash
GET /attio/v2/workspace_members
```

#### Get Workspace Member

```bash
GET /attio/v2/workspace_members/{workspace_member_id}
```

### Self (Token Info)

#### Identify Current Token

```bash
GET /attio/v2/self
```

Returns workspace info and OAuth scopes for the current access token.

### Comments

#### Create Comment on Record

```bash
POST /attio/v2/comments
Content-Type: application/json

{
  "data": {
    "format": "plaintext",
    "content": "This is a comment",
    "author": {
      "type": "workspace-member",
      "id": "{workspace_member_id}"
    },
    "record": {
      "object": "companies",
      "record_id": "{record_id}"
    }
  }
}
```

Required fields: `format`, `content`, `author`

Plus one of:
- `record`: Object with `object` slug and `record_id` (for record comments)
- `entry`: Object with `list` slug and `entry_id` (for list entry comments)
- `thread_id`: UUID of existing thread (for replies)

#### Reply to Comment Thread

```bash
POST /attio/v2/comments
Content-Type: application/json

{
  "data": {
    "format": "plaintext",
    "content": "This is a reply",
    "author": {
      "type": "workspace-member",
      "id": "{workspace_member_id}"
    },
    "thread_id": "{thread_id}"
  }
}
```

### Lists

#### List All Lists

```bash
GET /attio/v2/lists
```

#### Get List

```bash
GET /attio/v2/lists/{list_id}
```

### List Entries

#### Query List Entries

```bash
POST /attio/v2/lists/{list}/entries/query
Content-Type: application/json

{
  "limit": 50,
  "offset": 0,
  "filter": {},
  "sorts": []
}
```

Query parameters in body:
- `limit`: Maximum results (default 500)
- `offset`: Number of results to skip
- `filter`: Filter criteria object
- `sorts`: Array of sort specifications

#### Create List Entry

```bash
POST /attio/v2/lists/{list}/entries
Content-Type: application/json

{
  "data": {
    "parent_record_id": "{record_id}",
    "parent_object": "companies",
    "entry_values": {}
  }
}
```

#### Get List Entry

```bash
GET /attio/v2/lists/{list}/entries/{entry_id}
```

#### Update List Entry

```bash
PATCH /attio/v2/lists/{list}/entries/{entry_id}
Content-Type: application/json

{
  "data": {
    "entry_values": {
      "status": "Active"
    }
  }
}
```

#### Delete List Entry

```bash
DELETE /attio/v2/lists/{list}/entries/{entry_id}
```

### Notes

#### List Notes

```bash
GET /attio/v2/notes?limit=50
```

Query parameters:
- `limit`: Maximum results (default 10, max 50)
- `offset`: Number to skip
- `parent_object`: Object slug containing notes
- `parent_record_id`: Filter by specific record

#### Get Note

```bash
GET /attio/v2/notes/{note_id}
```

#### Create Note

```bash
POST /attio/v2/notes
Content-Type: application/json

{
  "data": {
    "format": "plaintext",
    "title": "Meeting Summary",
    "content": "Discussed Q1 goals and roadmap priorities.",
    "parent_object": "companies",
    "parent_record_id": "{record_id}",
    "created_by_actor": {
      "type": "workspace-member",
      "id": "{workspace_member_id}"
    }
  }
}
```

Required fields: `format`, `content`, `parent_object`, `parent_record_id`

#### Delete Note

```bash
DELETE /attio/v2/notes/{note_id}
```

### Meetings

#### List Meetings

```bash
GET /attio/v2/meetings?limit=50
```

Query parameters:
- `limit`: Maximum results (default 50, max 200)
- `cursor`: Pagination cursor from previous response

Uses cursor-based pagination.

#### Get Meeting

```bash
GET /attio/v2/meetings/{meeting_id}
```

### Call Recordings

Call recordings are accessed through meetings.

#### List Call Recordings for Meeting

```bash
GET /attio/v2/meetings/{meeting_id}/call_recordings?limit=50
```

Query parameters:
- `limit`: Maximum results (default 50, max 200)
- `cursor`: Pagination cursor from previous response

#### Get Call Recording

```bash
GET /attio/v2/meetings/{meeting_id}/call_recordings/{call_recording_id}
```

## Pagination

Attio supports two pagination methods:

### Limit/Offset Pagination

```bash
GET /attio/v2/tasks?limit=50&offset=0
GET /attio/v2/tasks?limit=50&offset=50
GET /attio/v2/tasks?limit=50&offset=100
```

### Cursor-Based Pagination (for some endpoints)

```bash
GET /attio/v2/meetings?limit=50
GET /attio/v2/meetings?limit=50&cursor={next_cursor}
```

Response includes `pagination.next_cursor` when more results exist.

## Code Examples

### JavaScript

```javascript
// Query company records
const response = await fetch(
  'https://gateway.maton.ai/attio/v2/objects/companies/records/query',
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ limit: 10 })
  }
);
const data = await response.json();
```

### Python

```python
import os
import requests

# Query company records
response = requests.post(
    'https://gateway.maton.ai/attio/v2/objects/companies/records/query',
    headers={'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'},
    json={'limit': 10}
)
data = response.json()
```

## Usage Notes

- Object slugs are lowercase snake_case (e.g., `people`, `companies`)
- Record IDs and other IDs are UUIDs
- For personal-name attributes, always include `full_name` when creating records
- Task creation requires `format: "plaintext"`, `deadline_at`, `assignees` array (can be empty), and `linked_records` array (can be empty)
- Note creation requires `format`, `content`, `parent_object`, and `parent_record_id`
- Comment creation requires `format`, `content`, `author`, plus one of `record`, `entry`, or `thread_id`
- Meetings use cursor-based pagination
- Some endpoints require additional OAuth scopes (lists, notes, webhooks)
- Rate limits: 100 read requests/second, 25 write requests/second
- Pagination uses `limit` and `offset` parameters (or `cursor` for meetings)
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing Attio connection or validation error |
| 401 | Invalid or missing Maton API key |
| 403 | Insufficient OAuth scopes |
| 404 | Resource not found |
| 429 | Rate limited |
| 4xx/5xx | Passthrough error from Attio API |

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

### Troubleshooting: Insufficient Scopes

If you receive a 403 error about missing scopes, contact Maton support at support@maton.ai with the specific operations/APIs you need and your use-case.

### Troubleshooting: Invalid App Name

1. Ensure your URL path starts with `attio`. For example:

- Correct: `https://gateway.maton.ai/attio/v2/objects`
- Incorrect: `https://gateway.maton.ai/v2/objects`

## Resources

- [Attio API Overview](https://docs.attio.com/rest-api/overview)
- [Attio API Reference](https://docs.attio.com/rest-api/endpoint-reference)
- [Records API](https://docs.attio.com/rest-api/endpoint-reference/records)
- [Objects API](https://docs.attio.com/rest-api/endpoint-reference/objects)
- [Tasks API](https://docs.attio.com/rest-api/endpoint-reference/tasks)
- [Rate Limiting](https://docs.attio.com/rest-api/guides/rate-limiting)
- [Pagination](https://docs.attio.com/rest-api/guides/pagination)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
