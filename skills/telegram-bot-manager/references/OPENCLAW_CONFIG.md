# OpenClaw Telegram Configuration Guide

## Prerequisites

- OpenClaw Gateway running
- Telegram Bot Token from BotFather
- Network access to api.telegram.org

## Configuration Steps

### 1. Get Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the prompts:
   - Bot name: e.g., "My OpenClaw Bot"
   - Bot username: e.g., "my_openclaw_bot" (must end with "bot")
4. Copy the token provided (format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Configure OpenClaw

Edit the OpenClaw configuration file:

```json
{
  "telegram": {
    "enabled": true,
    "token": "YOUR_BOT_TOKEN_HERE",
    "pairing": true,
    "streamMode": "partial"
  }
}
```

### 3. Enable Telegram Plugin

Add Telegram to your plugins:

```json
{
  "plugins": [
    "telegram"
  ]
}
```

### 4. Restart OpenClaw

```bash
openclaw gateway restart
```

### 5. Pair Your Device

1. Open Telegram and search for your bot
2. Send `/start` to the bot
3. The bot will provide pairing instructions
4. Follow the pairing process to link your Telegram account

## Configuration Options

### Basic Configuration

```json
{
  "telegram": {
    "enabled": true,
    "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
    "pairing": true,
    "streamMode": "partial"
  }
}
```

### Advanced Configuration

```json
{
  "telegram": {
    "enabled": true,
    "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
    "pairing": true,
    "streamMode": "partial",
    "webhook": {
      "enabled": false,
      "url": "https://your-domain.com/webhook",
      "secretToken": "your-secret-token"
    },
    "polling": {
      "interval": 1000,
      "timeout": 30
    }
  }
}
```

## Testing Configuration

### Check Telegram API Access

```bash
# Test basic connectivity
curl -I https://api.telegram.org

# Test bot token validity
curl -s "https://api.telegram.org/botYOUR_TOKEN/getMe"
```

### Verify OpenClaw Status

```bash
# Check OpenClaw status
openclaw status

# Check gateway status
openclaw gateway status
```

## Troubleshooting

### Network Issues

If you encounter "Connection timed out" errors:

1. **Check firewall rules**
   ```bash
   sudo ufw status
   ```

2. **Test DNS resolution**
   ```bash
   nslookup api.telegram.org
   ```

3. **Check proxy settings**
   ```bash
   echo $HTTP_PROXY
   echo $HTTPS_PROXY
   ```

### Configuration Issues

**Bot not responding:**
- Verify token is correct (no extra spaces)
- Check if bot is enabled in config
- Restart OpenClaw gateway

**Pairing issues:**
- Ensure `pairing: true` in config
- Check bot privacy settings
- Verify bot is not blocked

### Token Management

**To rotate token:**
1. Get new token from BotFather (`/token` command)
2. Update OpenClaw config
3. Restart gateway

**To revoke token:**
1. Use `/revoke` command in BotFather
2. Update config with new token if needed

## Security Best Practices

1. **Never commit tokens to version control**
   - Use environment variables: `TELEGRAM_BOT_TOKEN`
   - Or use secure config files outside repo

2. **Use different tokens for different environments**
   - Development: `@your_bot_dev`
   - Production: `@your_bot_prod`

3. **Regular token rotation**
   - Rotate tokens every 3-6 months
   - Revoke immediately if compromised

4. **Monitor bot activity**
   - Check logs for unusual patterns
   - Review bot usage statistics

## Environment Variables

Alternative to config file:

```bash
export TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
export TELEGRAM_ENABLED="true"
export TELEGRAM_PAIRING="true"
```

## Common Commands

### BotFather Commands

- `/newbot` - Create new bot
- `/mybots` - List your bots
- `/token` - Get new token
- `/revoke` - Revoke current token
- `/setdescription` - Set bot description
- `/setcommands` - Set bot commands

### OpenClaw Commands

```bash
# Restart OpenClaw
openclaw gateway restart

# Check status
openclaw status

# View logs
openclaw gateway logs
```

## Webhook Setup (Optional)

For production deployments, webhooks are more efficient than polling.

### Prerequisites

- Public HTTPS endpoint
- Valid SSL certificate
- OpenClaw accessible from internet

### Configuration

```json
{
  "telegram": {
    "webhook": {
      "enabled": true,
      "url": "https://your-domain.com/webhook",
      "secretToken": "your-secret-token"
    }
  }
}
```

### Set Webhook

```bash
curl -F "url=https://your-domain.com/webhook" \
     -F "secret_token=your-secret-token" \
     "https://api.telegram.org/botYOUR_TOKEN/setWebhook"
```

### Remove Webhook

```bash
curl "https://api.telegram.org/botYOUR_TOKEN/deleteWebhook"
```

## Testing Your Bot

### Manual Testing

1. Search for your bot username in Telegram
2. Send `/start` to begin conversation
3. Test basic commands

### Automated Testing

Use the test script in the skill:

```bash
python3 telegram-bot-manager/scripts/test_bot.py
```

## References

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [BotFather](https://t.me/BotFather)
- [OpenClaw Documentation](https://docs.openclaw.ai)
