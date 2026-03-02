---
name: one-drive
description: |
  OneDrive API integration with managed OAuth via Microsoft Graph. Manage files, folders, and sharing.
  Use this skill when users want to upload, download, organize, or share files in OneDrive.
  For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
  Requires network access and valid Maton API key.
metadata:
  author: maton
  version: "1.0"
  clawdbot:
    emoji: 🧠
    requires:
      env:
        - MATON_API_KEY
---

# OneDrive

Access the OneDrive API with managed OAuth authentication via Microsoft Graph. Manage files, folders, drives, and sharing with full CRUD operations.

## Quick Start

```bash
# List files in OneDrive root
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/one-drive/v1.0/me/drive/root/children')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/one-drive/v1.0/{resource}
```

The gateway proxies requests to `graph.microsoft.com` and automatically injects your OAuth token.

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

Manage your OneDrive OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=one-drive&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'one-drive'}).encode()
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
    "connection_id": "3f17fb58-4515-4840-8ef6-2bbf0fa67e2c",
    "status": "ACTIVE",
    "creation_time": "2026-02-07T08:23:30.317909Z",
    "last_updated_time": "2026-02-07T08:24:04.925298Z",
    "url": "https://connect.maton.ai/?session_token=...",
    "app": "one-drive",
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

If you have multiple OneDrive connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/one-drive/v1.0/me/drive')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '3f17fb58-4515-4840-8ef6-2bbf0fa67e2c')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### Drives

#### Get Current User's Drive

```bash
GET /one-drive/v1.0/me/drive
```

**Response:**
```json
{
  "id": "b!F3Y7M0VT80OO9iu_D6Z-LA...",
  "driveType": "personal",
  "name": "OneDrive",
  "owner": {
    "user": {
      "displayName": "John Doe",
      "id": "d4648f06c91d9d3d"
    }
  },
  "quota": {
    "total": 5368709120,
    "used": 1234567,
    "remaining": 5367474553
  }
}
```

#### List User's Drives

```bash
GET /one-drive/v1.0/me/drives
```

#### Get Drive by ID

```bash
GET /one-drive/v1.0/drives/{drive-id}
```

### Files and Folders

#### Get Drive Root

```bash
GET /one-drive/v1.0/me/drive/root
```

#### List Root Children

```bash
GET /one-drive/v1.0/me/drive/root/children
```

**Response:**
```json
{
  "value": [
    {
      "id": "F33B7653325337C3!s88...",
      "name": "Documents",
      "folder": {
        "childCount": 5
      },
      "createdDateTime": "2024-01-15T10:30:00Z",
      "lastModifiedDateTime": "2024-02-01T14:20:00Z"
    },
    {
      "id": "F33B7653325337C3!s3f...",
      "name": "report.pdf",
      "file": {
        "mimeType": "application/pdf",
        "hashes": {
          "sha1Hash": "cf23df2207d99a74fbe169e3eba035e633b65d94"
        }
      },
      "size": 35212
    }
  ]
}
```

#### Get Item by ID

```bash
GET /one-drive/v1.0/me/drive/items/{item-id}
```

#### Get Item by Path

Use colon (`:`) syntax to access items by path:

```bash
GET /one-drive/v1.0/me/drive/root:/Documents/report.pdf
```

#### List Folder Children by Path

```bash
GET /one-drive/v1.0/me/drive/root:/Documents:/children
```

#### Get Item Children

```bash
GET /one-drive/v1.0/me/drive/items/{item-id}/children
```

### Special Folders

Access known folders by name:

```bash
GET /one-drive/v1.0/me/drive/special/documents
GET /one-drive/v1.0/me/drive/special/photos
GET /one-drive/v1.0/me/drive/special/music
GET /one-drive/v1.0/me/drive/special/approot
```

### Recent and Shared

#### Get Recent Files

```bash
GET /one-drive/v1.0/me/drive/recent
```

#### Get Files Shared With Me

```bash
GET /one-drive/v1.0/me/drive/sharedWithMe
```

### Search

```bash
GET /one-drive/v1.0/me/drive/root/search(q='{query}')
```

Example:
```bash
GET /one-drive/v1.0/me/drive/root/search(q='budget')
```

### Create Folder

```bash
POST /one-drive/v1.0/me/drive/root/children
Content-Type: application/json

{
  "name": "New Folder",
  "folder": {},
  "@microsoft.graph.conflictBehavior": "rename"
}
```

Create folder inside another folder:
```bash
POST /one-drive/v1.0/me/drive/items/{parent-id}/children
Content-Type: application/json

{
  "name": "Subfolder",
  "folder": {}
}
```

### Upload File (Simple - up to 4MB)

```bash
PUT /one-drive/v1.0/me/drive/items/{parent-id}:/{filename}:/content
Content-Type: application/octet-stream

{file binary content}
```

Example - upload to root:
```bash
PUT /one-drive/v1.0/me/drive/root:/document.txt:/content
Content-Type: text/plain

Hello, OneDrive!
```

### Upload File (Large - resumable)

For files over 4MB, use resumable upload:

**Step 1: Create upload session**
```bash
POST /one-drive/v1.0/me/drive/root:/{filename}:/createUploadSession
Content-Type: application/json

{
  "item": {
    "@microsoft.graph.conflictBehavior": "rename"
  }
}
```

**Response:**
```json
{
  "uploadUrl": "https://sn3302.up.1drv.com/up/...",
  "expirationDateTime": "2024-02-08T10:00:00Z"
}
```

**Step 2: Upload bytes to the uploadUrl**

### Download File

Get the file metadata to retrieve the download URL:

```bash
GET /one-drive/v1.0/me/drive/items/{item-id}
```

The response includes `@microsoft.graph.downloadUrl` - a pre-authenticated URL valid for a short time:

```json
{
  "id": "...",
  "name": "document.pdf",
  "@microsoft.graph.downloadUrl": "https://public-sn3302.files.1drv.com/..."
}
```

Use this URL directly to download the file content (no auth header needed).

### Update Item (Rename/Move)

```bash
PATCH /one-drive/v1.0/me/drive/items/{item-id}
Content-Type: application/json

{
  "name": "new-name.txt"
}
```

Move to different folder:
```bash
PATCH /one-drive/v1.0/me/drive/items/{item-id}
Content-Type: application/json

{
  "parentReference": {
    "id": "{new-parent-id}"
  }
}
```

### Copy Item

```bash
POST /one-drive/v1.0/me/drive/items/{item-id}/copy
Content-Type: application/json

{
  "parentReference": {
    "id": "{destination-folder-id}"
  },
  "name": "copied-file.txt"
}
```

Returns `202 Accepted` with a `Location` header to monitor the copy operation.

### Delete Item

```bash
DELETE /one-drive/v1.0/me/drive/items/{item-id}
```

Returns `204 No Content` on success.

### Sharing

#### Create Sharing Link

```bash
POST /one-drive/v1.0/me/drive/items/{item-id}/createLink
Content-Type: application/json

{
  "type": "view",
  "scope": "anonymous"
}
```

Link types:
- `view` - Read-only access
- `edit` - Read-write access
- `embed` - Embeddable link

Scopes:
- `anonymous` - Anyone with the link
- `organization` - Anyone in your organization

**Response:**
```json
{
  "id": "...",
  "link": {
    "type": "view",
    "scope": "anonymous",
    "webUrl": "https://1drv.ms/b/..."
  }
}
```

#### Invite Users (Share with specific people)

```bash
POST /one-drive/v1.0/me/drive/items/{item-id}/invite
Content-Type: application/json

{
  "recipients": [
    {"email": "user@example.com"}
  ],
  "roles": ["read"],
  "sendInvitation": true,
  "message": "Check out this file!"
}
```

## Query Parameters

Customize responses with OData query parameters:

- `$select` - Choose specific properties: `?$select=id,name,size`
- `$expand` - Include related resources: `?$expand=children`
- `$filter` - Filter results: `?$filter=file ne null` (files only)
- `$orderby` - Sort results: `?$orderby=name`
- `$top` - Limit results: `?$top=10`

Example:
```bash
GET /one-drive/v1.0/me/drive/root/children?$select=id,name,size&$top=20&$orderby=name
```

## Pagination

Results are paginated. The response includes `@odata.nextLink` for additional pages:

```json
{
  "value": [...],
  "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=..."
}
```

Use the full URL from `@odata.nextLink` (without the gateway prefix) to fetch the next page.

## Code Examples

### JavaScript

```javascript
// List files in root
const response = await fetch(
  'https://gateway.maton.ai/one-drive/v1.0/me/drive/root/children',
  {
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`
    }
  }
);
const data = await response.json();

// Upload a file
const uploadResponse = await fetch(
  'https://gateway.maton.ai/one-drive/v1.0/me/drive/root:/myfile.txt:/content',
  {
    method: 'PUT',
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`,
      'Content-Type': 'text/plain'
    },
    body: 'Hello, OneDrive!'
  }
);
```

### Python

```python
import os
import requests

# List files in root
response = requests.get(
    'https://gateway.maton.ai/one-drive/v1.0/me/drive/root/children',
    headers={'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'}
)
files = response.json()

# Upload a file
upload_response = requests.put(
    'https://gateway.maton.ai/one-drive/v1.0/me/drive/root:/myfile.txt:/content',
    headers={
        'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}',
        'Content-Type': 'text/plain'
    },
    data='Hello, OneDrive!'
)
```

## Notes

- OneDrive uses Microsoft Graph API (`graph.microsoft.com`)
- Item IDs are unique within a drive
- Use colon (`:`) syntax for path-based addressing: `/root:/path/to/file`
- Simple uploads are limited to 4MB; use resumable upload for larger files
- Download URLs from `@microsoft.graph.downloadUrl` are pre-authenticated and temporary
- Conflict behavior options: `fail`, `replace`, `rename`
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing OneDrive connection or invalid request |
| 401 | Invalid or missing Maton API key |
| 403 | Insufficient permissions |
| 404 | Item not found |
| 409 | Conflict (e.g., item already exists) |
| 429 | Rate limited (check `Retry-After` header) |
| 4xx/5xx | Passthrough error from Microsoft Graph API |

### Error Response Format

```json
{
  "error": {
    "code": "itemNotFound",
    "message": "The resource could not be found."
  }
}
```

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

1. Ensure your URL path starts with `one-drive`. For example:

- Correct: `https://gateway.maton.ai/one-drive/v1.0/me/drive/root/children`
- Incorrect: `https://gateway.maton.ai/v1.0/me/drive/root/children`

## Resources

- [OneDrive Developer Documentation](https://learn.microsoft.com/en-us/onedrive/developer/)
- [Microsoft Graph API Reference](https://learn.microsoft.com/en-us/graph/api/overview)
- [DriveItem Resource](https://learn.microsoft.com/en-us/graph/api/resources/driveitem)
- [Drive Resource](https://learn.microsoft.com/en-us/graph/api/resources/drive)
- [Sharing and Permissions](https://learn.microsoft.com/en-us/onedrive/developer/rest-api/concepts/sharing)
- [Large File Upload](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
