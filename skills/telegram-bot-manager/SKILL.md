---
name: telegram-bot-manager
description: Manage and configure Telegram bots for OpenClaw. Use when setting up Telegram integrations, troubleshooting bot connectivity, configuring bot tokens, or managing Telegram channel/webhook settings. Handles bot registration, token validation, and network connectivity checks for api.telegram.org.
---

# Telegram Bot Manager

## Quick Start

### Setup a new Telegram bot

1. **Create bot via BotFather**
   - Message @BotFather on Telegram
   - Use `/newbot` command
   - Follow prompts for bot name and username
   - Copy the bot token (format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Configure in OpenClaw**
   - Add token to OpenClaw config
   - Enable Telegram plugin
   - Set up pairing mode for DM access

### Validate bot configuration

```bash
# Test Telegram API connectivity
curl -I https://api.telegram.org

# Check bot token validity
curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"
```

## Common Workflows

### Troubleshooting connectivity issues

When api.telegram.org is unreachable:

1. **Check network access**
   ```bash
   curl -I -m 10 https://api.telegram.org
   ```

2. **Verify DNS resolution**
   ```bash
   nslookup api.telegram.org
   ```

3. **Test alternative endpoints**
   ```bash
   curl -I https://telegram.org
   ```

### Configuring OpenClaw Telegram integration

See [OPENCLAW_CONFIG.md](references/OPENCLAW_CONFIG.md) for detailed configuration steps.

### Bot token security

- Never commit bot tokens to version control
- Store tokens in environment variables or secure config files
- Rotate tokens if compromised
- Use different tokens for different environments (dev/prod)

## Bot Commands Reference

Common Telegram bot commands for BotFather:

- `/newbot` - Create a new bot
- `/mybots` - Manage your bots
- `/setdescription` - Set bot description
- `/setabouttext` - Set about text
- `/setuserpic` - Set bot profile picture
- `/setcommands` - Set bot commands
- `/token` - Generate new token
- `/revoke` - Revoke current token
- `/setprivacy` - Configure privacy mode

## Webhook vs Polling

### Webhook (Recommended for production)
- Bot receives updates via HTTP POST
- Requires public HTTPS endpoint
- More efficient for high-volume bots

### Polling (Good for development)
- Bot continuously checks for updates
- Simpler setup, no public endpoint needed
- Easier to debug locally

See [WEBHOOK_SETUP.md](references/WEBHOOK_SETUP.md) for webhook configuration.

## Error Handling

### Common errors and solutions

**"Connection timed out"**
- Check firewall rules
- Verify proxy configuration
- Test with different network

**"Invalid token"**
- Verify token format (should contain colon)
- Check for extra spaces or characters
- Regenerate token if needed

**"Bot not responding"**
- Verify bot is not blocked
- Check bot privacy settings
- Ensure bot has proper permissions

## Testing Your Bot

### Manual testing
1. Search for your bot username on Telegram
2. Start a conversation with `/start`
3. Test basic commands

### Automated testing
Use the test script in `scripts/test_bot.py` for automated validation.

## References

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [BotFather Documentation](https://core.telegram.org/bots#6-botfather)
- [OpenClaw Configuration Guide](references/OPENCLAW_CONFIG.md)
