---
name: salesforce
description: |
  Salesforce CRM API integration with managed OAuth. Query records with SOQL, manage sObjects (Contacts, Accounts, Leads, Opportunities), and perform batch operations. Use this skill when users want to interact with Salesforce data. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
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

# Salesforce

Access the Salesforce REST API with managed OAuth authentication. Query records using SOQL, manage sObjects, and perform CRUD operations on your Salesforce data.

## Quick Start

```bash
# Query contacts
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/salesforce/services/data/v59.0/query?q=SELECT+Id,Name,Email+FROM+Contact+LIMIT+10')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/salesforce/{native-api-path}
```

Replace `{native-api-path}` with the actual Salesforce REST API endpoint path. The gateway proxies requests to `{instance}.salesforce.com` (automatically replaced with your connection config) and injects your access token.

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

Manage your Salesforce OAuth connections at `https://ctrl.maton.ai`.

### List Connections

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=salesforce&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'salesforce'}).encode()
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
    "app": "salesforce",
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

If you have multiple Salesforce connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/salesforce/services/data/v59.0/sobjects')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### SOQL Query

```bash
GET /salesforce/services/data/v59.0/query?q=SELECT+Id,Name+FROM+Contact+LIMIT+10
```

Complex query:

```bash
GET /salesforce/services/data/v59.0/query?q=SELECT+Id,Name,Email+FROM+Contact+WHERE+Email+LIKE+'%example.com'+ORDER+BY+CreatedDate+DESC
```

### Get Object

```bash
GET /salesforce/services/data/v59.0/sobjects/{objectType}/{recordId}
```

Example:

```bash
GET /salesforce/services/data/v59.0/sobjects/Contact/003XXXXXXXXXXXXXXX
```

### Create Object

```bash
POST /salesforce/services/data/v59.0/sobjects/{objectType}
Content-Type: application/json

{
  "FirstName": "John",
  "LastName": "Doe",
  "Email": "john@example.com"
}
```

### Update Object

```bash
PATCH /salesforce/services/data/v59.0/sobjects/{objectType}/{recordId}
Content-Type: application/json

{
  "Phone": "+1234567890"
}
```

### Delete Object

```bash
DELETE /salesforce/services/data/v59.0/sobjects/{objectType}/{recordId}
```

### Describe Object (get schema)

```bash
GET /salesforce/services/data/v59.0/sobjects/{objectType}/describe
```

### List Objects

```bash
GET /salesforce/services/data/v59.0/sobjects
```

### Search (SOSL)

```bash
GET /salesforce/services/data/v59.0/search?q=FIND+{searchTerm}+IN+ALL+FIELDS+RETURNING+Contact(Id,Name)
```

### Composite Request (batch multiple operations)

```bash
POST /salesforce/services/data/v59.0/composite
Content-Type: application/json

{
  "compositeRequest": [
    {
      "method": "GET",
      "url": "/services/data/v59.0/sobjects/Contact/003XXXXXXX",
      "referenceId": "contact1"
    },
    {
      "method": "GET",
      "url": "/services/data/v59.0/sobjects/Account/001XXXXXXX",
      "referenceId": "account1"
    }
  ]
}
```

### Composite Batch Request

```bash
POST /salesforce/services/data/v59.0/composite/batch
Content-Type: application/json

{
  "batchRequests": [
    {"method": "GET", "url": "v59.0/sobjects/Contact/003XXXXXXX"},
    {"method": "GET", "url": "v59.0/sobjects/Account/001XXXXXXX"}
  ]
}
```

### sObject Collections Create (batch create)

```bash
POST /salesforce/services/data/v59.0/composite/sobjects
Content-Type: application/json

{
  "allOrNone": true,
  "records": [
    {"attributes": {"type": "Contact"}, "FirstName": "John", "LastName": "Doe"},
    {"attributes": {"type": "Contact"}, "FirstName": "Jane", "LastName": "Smith"}
  ]
}
```

### sObject Collections Delete (batch delete)

```bash
DELETE /salesforce/services/data/v59.0/composite/sobjects?ids=003XXXXX,003YYYYY&allOrNone=true
```

### Get Updated Records

```bash
GET /salesforce/services/data/v59.0/sobjects/{objectType}/updated/?start=2026-01-30T00:00:00Z&end=2026-02-01T00:00:00Z
```

### Get Deleted Records

```bash
GET /salesforce/services/data/v59.0/sobjects/{objectType}/deleted/?start=2026-01-30T00:00:00Z&end=2026-02-01T00:00:00Z
```

### Get API Limits

```bash
GET /salesforce/services/data/v59.0/limits
```

### List API Versions

```bash
GET /salesforce/services/data/
```

## Common Objects

- `Account` - Companies/Organizations
- `Contact` - People associated with accounts
- `Lead` - Potential customers
- `Opportunity` - Sales deals
- `Case` - Support cases
- `Task` - To-do items
- `Event` - Calendar events

## Code Examples

### JavaScript

```javascript
const response = await fetch(
  'https://gateway.maton.ai/salesforce/services/data/v59.0/query?q=SELECT+Id,Name+FROM+Contact+LIMIT+5',
  {
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`
    }
  }
);
const data = await response.json();
```

### Python

```python
import os
import requests

response = requests.get(
    'https://gateway.maton.ai/salesforce/services/data/v59.0/query',
    headers={'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'},
    params={'q': 'SELECT Id,Name FROM Contact LIMIT 5'}
)
```

## Notes

- Use URL encoding for SOQL queries (spaces become `+`)
- Record IDs are 15 or 18 character alphanumeric strings
- API version (v59.0) can be adjusted; latest is v65.0
- Update and Delete operations return HTTP 204 (no content) on success
- Dates for updated/deleted queries use ISO 8601 format: `YYYY-MM-DDTHH:MM:SSZ`
- Use `allOrNone: true` in batch operations for atomic transactions
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets (`fields[]`, `sort[]`, `records[]`) to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing Salesforce connection |
| 401 | Invalid or missing Maton API key |
| 429 | Rate limited (10 req/sec per account) |
| 4xx/5xx | Passthrough error from Salesforce API |

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

1. Ensure your URL path starts with `salesforce`. For example:

- Correct: `https://gateway.maton.ai/salesforce/services/data/v59.0/query`
- Incorrect: `https://gateway.maton.ai/services/data/v59.0/query`

## Resources

- [REST API Developer Guide](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_rest.htm)
- [List sObjects](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_describeGlobal.htm)
- [Describe sObject](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_describe.htm)
- [Get Record](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_retrieve_get.htm)
- [Create Record](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_sobject_create.htm)
- [Update Record](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_update_fields.htm)
- [Delete Record](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_delete_record.htm)
- [Query Records (SOQL)](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_query.htm)
- [Composite Request](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_composite_composite_post.htm)
- [sObject Collections](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_composite_sobjects_collections_create.htm)
- [SOQL Reference](https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql.htm)
- [SOSL Reference](https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_sosl.htm)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
