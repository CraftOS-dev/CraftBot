---
name: google-play
description: |
  Google Play Developer API (Android Publisher) integration with managed OAuth. Manage apps, subscriptions, in-app purchases, and reviews. Use this skill when users want to interact with Google Play Console programmatically. For other third party apps, use the api-gateway skill (https://clawhub.ai/byungkyu/api-gateway).
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

# Google Play

Access the Google Play Developer API (Android Publisher) with managed OAuth authentication. Manage app listings, subscriptions, in-app purchases, reviews, and more.

## Quick Start

```bash
# List in-app products
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/google-play/androidpublisher/v3/applications/{packageName}/inappproducts')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

## Base URL

```
https://gateway.maton.ai/google-play/{native-api-path}
```

Replace `{native-api-path}` with the actual Android Publisher API endpoint path. The gateway proxies requests to `androidpublisher.googleapis.com` and automatically injects your OAuth token.

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
req = urllib.request.Request('https://ctrl.maton.ai/connections?app=google-play&status=ACTIVE')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

### Create Connection

```bash
python <<'EOF'
import urllib.request, os, json
data = json.dumps({'app': 'google-play'}).encode()
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
    "app": "google-play",
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

If you have multiple Google Play connections, specify which one to use with the `Maton-Connection` header:

```bash
python <<'EOF'
import urllib.request, os, json
req = urllib.request.Request('https://gateway.maton.ai/google-play/androidpublisher/v3/applications/{packageName}/inappproducts')
req.add_header('Authorization', f'Bearer {os.environ["MATON_API_KEY"]}')
req.add_header('Maton-Connection', '21fd90f9-5935-43cd-b6c8-bde9d915ca80')
print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))
EOF
```

If omitted, the gateway uses the default (oldest) active connection.

## API Reference

### In-App Products

#### List In-App Products

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/inappproducts
```

#### Get In-App Product

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/inappproducts/{sku}
```

#### Create In-App Product

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/inappproducts
Content-Type: application/json

{
  "packageName": "com.example.app",
  "sku": "premium_upgrade",
  "status": "active",
  "purchaseType": "managedUser",
  "defaultPrice": {
    "priceMicros": "990000",
    "currency": "USD"
  },
  "listings": {
    "en-US": {
      "title": "Premium Upgrade",
      "description": "Unlock all premium features"
    }
  }
}
```

#### Update In-App Product

```bash
PUT /google-play/androidpublisher/v3/applications/{packageName}/inappproducts/{sku}
Content-Type: application/json

{
  "packageName": "com.example.app",
  "sku": "premium_upgrade",
  "status": "active",
  "purchaseType": "managedUser",
  "defaultPrice": {
    "priceMicros": "1990000",
    "currency": "USD"
  }
}
```

#### Delete In-App Product

```bash
DELETE /google-play/androidpublisher/v3/applications/{packageName}/inappproducts/{sku}
```

### Subscriptions

#### List Subscriptions

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/subscriptions
```

#### Get Subscription

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/subscriptions/{productId}
```

#### Create Subscription

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/subscriptions
Content-Type: application/json

{
  "productId": "monthly_premium",
  "basePlans": [
    {
      "basePlanId": "p1m",
      "autoRenewingBasePlanType": {
        "billingPeriodDuration": "P1M"
      }
    }
  ],
  "listings": [
    {
      "languageCode": "en-US",
      "title": "Premium Monthly"
    }
  ]
}
```

### Purchases

#### Get Purchase (one-time product)

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/purchases/products/{productId}/tokens/{token}
```

#### Acknowledge Purchase

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/purchases/products/{productId}/tokens/{token}:acknowledge
Content-Type: application/json

{
  "developerPayload": "optional payload"
}
```

#### Get Subscription Purchase

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/purchases/subscriptions/{subscriptionId}/tokens/{token}
```

#### Cancel Subscription

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/purchases/subscriptions/{subscriptionId}/tokens/{token}:cancel
```

#### Refund Subscription

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/purchases/subscriptions/{subscriptionId}/tokens/{token}:refund
```

### Reviews

#### List Reviews

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/reviews
```

#### Get Review

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/reviews/{reviewId}
```

#### Reply to Review

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/reviews/{reviewId}:reply
Content-Type: application/json

{
  "replyText": "Thank you for your feedback!"
}
```

### Edits (App Updates)

#### Create Edit

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/edits
```

#### Get Edit

```bash
GET /google-play/androidpublisher/v3/applications/{packageName}/edits/{editId}
```

#### Commit Edit

```bash
POST /google-play/androidpublisher/v3/applications/{packageName}/edits/{editId}:commit
```

#### Delete Edit

```bash
DELETE /google-play/androidpublisher/v3/applications/{packageName}/edits/{editId}
```

## Code Examples

### JavaScript

```javascript
// List in-app products
const packageName = 'com.example.app';
const response = await fetch(
  `https://gateway.maton.ai/google-play/androidpublisher/v3/applications/${packageName}/inappproducts`,
  {
    headers: {
      'Authorization': `Bearer ${process.env.MATON_API_KEY}`
    }
  }
);

const products = await response.json();
console.log(products);
```

### Python

```python
import os
import requests

headers = {'Authorization': f'Bearer {os.environ["MATON_API_KEY"]}'}
package_name = 'com.example.app'

# List in-app products
response = requests.get(
    f'https://gateway.maton.ai/google-play/androidpublisher/v3/applications/{package_name}/inappproducts',
    headers=headers
)
products = response.json()
print(products)
```

## Notes

- Replace `{packageName}` with your app's package name (e.g., `com.example.app`)
- The Google Play Developer API requires the app to be published on Google Play
- Subscription management requires the app to have active subscriptions configured
- Edits are transactional - create an edit, make changes, then commit
- IMPORTANT: When using curl commands, use `curl -g` when URLs contain brackets (`fields[]`, `sort[]`, `records[]`) to disable glob parsing
- IMPORTANT: When piping curl output to `jq` or other commands, environment variables like `$MATON_API_KEY` may not expand correctly in some shell environments. You may get "Invalid API key" errors when piping.

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Missing Google Play connection |
| 401 | Invalid or missing Maton API key |
| 404 | Package not found or no access |
| 429 | Rate limited (10 req/sec per account) |
| 4xx/5xx | Passthrough error from Google Play API |

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

1. Ensure your URL path starts with `google-play`. For example:

- Correct: `https://gateway.maton.ai/google-play/androidpublisher/v3/applications/{packageName}/inappproducts`
- Incorrect: `https://gateway.maton.ai/androidpublisher/v3/applications/{packageName}/inappproducts`

## Resources

- [Android Publisher API Overview](https://developers.google.com/android-publisher)
- [In-App Products](https://developers.google.com/android-publisher/api-ref/rest/v3/inappproducts)
- [Subscriptions](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.subscriptions)
- [Purchases](https://developers.google.com/android-publisher/api-ref/rest/v3/purchases.products)
- [Reviews](https://developers.google.com/android-publisher/api-ref/rest/v3/reviews)
- [Edits](https://developers.google.com/android-publisher/api-ref/rest/v3/edits)
- [Maton Community](https://discord.com/invite/dBfFAcefs2)
- [Maton Support](mailto:support@maton.ai)
