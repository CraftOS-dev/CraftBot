---
name: google-meet
description: |
  Google Meet API integration with managed OAuth. Create meeting spaces, list conference records, and manage meeting participants. Use this skill when users want to interact with Google Meet. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
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

# Google Meet

Access the Google Meet API with managed OAuth authentication. Create and manage meeting spaces, list conference records, and retrieve participant information.

## Quick Start

```bash
# Create a meeting space
python <<'EOF'
import urllib.request, os, json
data = json.dumps({}).encode()
req = urllib.request.Request('https://gateway.maton.ai/google-meet/v2/spaces', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Content-Type', 'application/json')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/google-meet/{native-api-path}
```

Replace `{native-api-path}` with the actual Google Meet API endpoint path. The gateway proxies requests to `meet.googleapis.com` and automatically injects your OAuth token.

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

Manage your Google OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=google-meet&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'google-meet'}).encode()
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
    "app": "google-meet",
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

If you have multiple Google Meet connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({}).encode()
req = urllib.request.Request('https://gateway.maton.ai/google-meet/v2/spaces', data=data, method='POST')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Content-Type', 'application/json')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Spaces

#### Create Space

```bash
POST /google-meet/v2/spaces
Content-Type: application/json

{}
```

**Response:**
```json
{
  "name": "spaces/abc123",
  "meetingUri": "https://meet.google.com/abc-defg-hij",
  "meetingCode": "abc-defg-hij",
  "config": {
    "accessType": "OPEN",
    "entryPointAccess": "ALL"
  }
}
```

#### Get Space

```bash
GET /google-meet/v2/spaces/{spaceId}
```

#### Update Space

```bash
PATCH /google-meet/v2/spaces/{spaceId}
Content-Type: application/json

{
  "config": {
    "accessType": "TRUSTED"
  }
}
```

#### End Active Call

```bash
POST /google-meet/v2/spaces/{spaceId}:endActiveConference
```

### Conference Records

#### List Conference Records

```bash
GET /google-meet/v2/conferenceRecords
```

With filter:

```bash
GET /google-meet/v2/conferenceRecords?filter=space.name="spaces/abc123"
```

#### Get Conference Record

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}
```

### Participants

#### List Participants

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/participants
```

#### Get Participant

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/participants/{participantId}
```

### Participant Sessions

#### List Participant Sessions

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/participants/{participantId}/participantSessions
```

### Recordings

#### List Recordings

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/recordings
```

#### Get Recording

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/recordings/{recordingId}
```

### Transcripts

#### List Transcripts

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/transcripts
```

#### Get Transcript

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/transcripts/{transcriptId}
```

#### List Transcript Entries

```bash
GET /google-meet/v2/conferenceRecords/{conferenceRecordId}/transcripts/{transcriptId}/entries
```

## Code Examples

### JavaScript

```javascript
// Create a meeting space
const response = await fetch(
  'https://gateway.maton.ai/google-meet/v2/spaces',
  {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`
    },
    body: JSON.stringify({})
  }
);

const space = await response.json();
console.log(`Meeting URL: ${space.meetingUri}`);
```

### Python

```python
import os
import requests

headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'
}

# Create a meeting space
response = requests.post(
    'https://gateway.maton.ai/google-meet/v2/spaces',
    headers=headers,
    json={}
)
space = response.json()
print(f"Meeting URL: {space['meetingUri']}")
```

## Notes

- Spaces are persistent meeting rooms that can be reused
- Conference records are created when a meeting starts and track meeting history
- Access types: `OPEN` (anyone with link), `TRUSTED` (organization members only), `RESTRICTED` (invited only)
- Recordings and transcripts require Google Workspace with recording enabled
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing Google Meet connection |
| 401 | Invalid or missing Maton API key |
| 429 | Rate limited (10 req/sec per account) |
| 4xx/5xx | Passthrough error from Google Meet API |

### Troubleshooting: Invalid API Key

**When you receive a "Invalid API key" error, ALWAYS follow these steps before concluding there is an issue:**

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

1. Ensure your URL path starts with `google-meet`. For example:

- Correct: `https://gateway.maton.ai/google-meet/v2/spaces`
- Incorrect: `https://gateway.maton.ai/meet/v2/spaces`

## Resources

- [Google Meet API Overview](https://developers.google.com/meet/api/reference/rest)
- [Spaces](https://developers.google.com/meet/api/reference/rest/v2/spaces)
- [Conference Records](https://developers.google.com/meet/api/reference/rest/v2/conferenceRecords)
- [Participants](https://developers.google.com/meet/api/reference/rest/v2/conferenceRecords.participants)
- [Recordings](https://developers.google.com/meet/api/reference/rest/v2/conferenceRecords.recordings)
- [Transcripts](https://developers.google.com/meet/api/reference/rest/v2/conferenceRecords.transcripts)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
