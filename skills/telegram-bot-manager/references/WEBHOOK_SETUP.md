# Telegram Webhook Setup Guide

## Overview

Webhooks provide a more efficient way for Telegram bots to receive updates compared to polling. Instead of continuously checking for new messages, Telegram sends updates directly to your bot's webhook URL.

## When to Use Webhooks

**Use webhooks when:**
- Running a production bot
- High message volume expected
- You have a public HTTPS endpoint
- Want to reduce server load

**Use polling when:**
- Developing locally
- Testing and debugging
- Behind firewall/NAT
- Low message volume

## Prerequisites

### Required

1. **Public HTTPS endpoint**
   - Domain name (e.g., `your-domain.com`)
   - Valid SSL certificate (Let's Encrypt, commercial, etc.)
   - OpenClaw accessible from internet

2. **OpenClaw configuration**
   - Telegram plugin enabled
   - Bot token from BotFather

### Optional but Recommended

- Reverse proxy (nginx, Apache)
- Load balancer
- Monitoring and logging

## Step-by-Step Setup

### 1. Prepare Your Server

#### Domain and SSL

```bash
# Get domain (example using Cloudflare)
# Set up DNS A record pointing to your server IP

# Install certbot for Let's Encrypt
sudo apt update
sudo apt install certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com
```

#### Firewall Configuration

```bash
# Allow HTTPS traffic
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp  # For certbot renewal
```

### 2. Configure OpenClaw

Edit your OpenClaw configuration:

```json
{
  "telegram": {
    "enabled": true,
    "token": "YOUR_BOT_TOKEN",
    "pairing": true,
    "streamMode": "partial",
    "webhook": {
      "enabled": true,
      "url": "https://your-domain.com/webhook",
      "secretToken": "your-secret-token-here"
    }
  }
}
```

**Important:** The `secretToken` should be a random string that Telegram will include in the `X-Telegram-Bot-Api-Secret-Token` header. This helps verify that webhook requests are actually from Telegram.

### 3. Set Up Webhook with Telegram

#### Method 1: Using curl

```bash
# Set webhook
curl -F "url=https://your-domain.com/webhook" \
     -F "secret_token=your-secret-token-here" \
     "https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook"

# Check webhook status
curl "https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo"
```

#### Method 2: Using OpenClaw

After configuring OpenClaw and restarting, the Telegram plugin will automatically set the webhook.

### 4. Configure Reverse Proxy (nginx example)

Create nginx configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    location /webhook {
        # Verify Telegram secret token
        if ($http_x_telegram_bot_api_secret_token != "your-secret-token-here") {
            return 403;
        }

        # Proxy to OpenClaw
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        # Timeout settings
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
```

Test and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Restart OpenClaw

```bash
openclaw gateway restart
```

### 6. Test Webhook

#### Health Check

```bash
curl https://your-domain.com/health
```

#### Send Test Message

1. Open Telegram
2. Search for your bot
3. Send `/start` or any message
4. Check OpenClaw logs for incoming updates

```bash
openclaw gateway logs -f
```

## Webhook Security

### Secret Token Verification

Always use a strong secret token:

```bash
# Generate random secret
openssl rand -base64 32
```

### IP Whitelisting (Optional)

Telegram webhook requests come from these IP ranges:

- `149.154.160.0/20`
- `91.108.4.0/22`

You can whitelist these in your firewall or nginx:

```nginx
location /webhook {
    # Telegram IP ranges
    allow 149.154.160.0/20;
    allow 91.108.4.0/22;
    deny all;

    # ... rest of config
}
```

### Rate Limiting

Protect against abuse:

```nginx
limit_req_zone $binary_remote_addr zone=telegram:10m rate=10r/s;

location /webhook {
    limit_req zone=telegram burst=20 nodelay;
    # ... rest of config
}
```

## Monitoring and Debugging

### Check Webhook Status

```bash
# Get webhook info
curl "https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo"

# Expected response:
# {
#   "ok": true,
#   "result": {
#     "url": "https://your-domain.com/webhook",
#     "has_custom_certificate": false,
#     "pending_update_count": 0,
#     "max_connections": 40
#   }
# }
```

### View Logs

```bash
# OpenClaw logs
openclaw gateway logs -f

# Nginx access logs
sudo tail -f /var/log/nginx/access.log

# Nginx error logs
sudo tail -f /var/log/nginx/error.log
```

### Common Issues

#### 403 Forbidden

**Cause:** Secret token mismatch or IP not whitelisted

**Solution:**
- Verify secret token in config matches nginx
- Check Telegram IP ranges in firewall

#### 404 Not Found

**Cause:** Wrong webhook URL path

**Solution:**
- Ensure webhook URL ends with `/webhook`
- Check nginx location block

#### Timeout Errors

**Cause:** OpenClaw not responding or slow

**Solution:**
- Increase proxy timeouts in nginx
- Check OpenClaw gateway status
- Review system resources

#### SSL Certificate Errors

**Cause:** Invalid or expired certificate

**Solution:**
- Renew certificate: `sudo certbot renew`
- Verify certificate chain: `openssl s_client -connect your-domain.com:443`

## Advanced Configuration

### Multiple Webhook Endpoints

For different bot instances:

```json
{
  "telegram": {
    "bots": [
      {
        "token": "BOT1_TOKEN",
        "webhook": {
          "enabled": true,
          "url": "https://your-domain.com/webhook/bot1",
          "secretToken": "secret1"
        }
      },
      {
        "token": "BOT2_TOKEN",
        "webhook": {
          "enabled": true,
          "url": "https://your-domain.com/webhook/bot2",
          "secretToken": "secret2"
        }
      }
    ]
  }
}
```

### Load Balancing

For high-traffic bots:

```nginx
upstream openclaw_backend {
    server 127.0.0.1:3000;
    server 127.0.0.1:3001;
    server 127.0.0.1:3002;
}

location /webhook {
    proxy_pass http://openclaw_backend;
    # ... rest of config
}
```

### Health Monitoring

Create a monitoring script:

```bash
#!/bin/bash
# monitor-webhook.sh

WEBHOOK_URL="https://your-domain.com/webhook"
BOT_TOKEN="YOUR_BOT_TOKEN"

# Check webhook status
STATUS=$(curl -s "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo" | jq -r '.result.url')

if [ "$STATUS" = "$WEBHOOK_URL" ]; then
    echo "Webhook is active"
else
    echo "Webhook is not set correctly"
    # Send alert
fi
```

## Switching Between Webhook and Polling

### To Switch to Polling

1. Disable webhook in Telegram:

```bash
curl "https://api.telegram.org/botYOUR_BOT_TOKEN/deleteWebhook"
```

2. Update OpenClaw config:

```json
{
  "telegram": {
    "webhook": {
      "enabled": false
    }
  }
}
```

3. Restart OpenClaw:

```bash
openclaw gateway restart
```

### To Switch to Webhook

Follow the setup steps above.

## Performance Optimization

### Webhook Queue Management

For high-volume bots, consider:

1. **Async processing**: Ensure OpenClaw processes webhooks asynchronously
2. **Queue system**: Use Redis or similar for message queuing
3. **Database optimization**: Optimize database queries for webhook processing

### Monitoring Metrics

Track these metrics:

- Webhook response time
- Pending updates count
- Error rates
- Message throughput

## References

- [Telegram Webhook Documentation](https://core.telegram.org/bots/webhooks)
- [Telegram IP Ranges](https://core.telegram.org/bots/webhooks#the-short-version)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Nginx Reverse Proxy Guide](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
