# Telegram Bot Manager Skill

A comprehensive skill for managing Telegram bots in OpenClaw. This skill provides tools, scripts, and documentation for setting up, configuring, and troubleshooting Telegram bot integrations.

## Features

- **Bot Setup Automation**: Scripts to automate bot configuration
- **Connectivity Testing**: Tools to test Telegram API access
- **Webhook Management**: Complete guide for webhook setup
- **Troubleshooting**: Common issues and solutions
- **Security Best Practices**: Token management and security guidelines

## Quick Start

### 1. Install the Skill

```bash
clawhub install telegram-bot-manager
```

### 2. Get Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the prompts to create your bot
4. Copy the bot token

### 3. Run Setup

```bash
python3 telegram-bot-manager/scripts/setup_bot.py
```

Or manually:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token"
python3 telegram-bot-manager/scripts/setup_bot.py
```

### 4. Test Your Bot

```bash
python3 telegram-bot-manager/scripts/test_bot.py
```

## Skill Contents

### Scripts

- **setup_bot.py**: Automated bot setup and configuration
- **test_bot.py**: Comprehensive bot testing and validation
- **package_skill.py**: Package skill for ClawHub distribution

### References

- **OPENCLAW_CONFIG.md**: Detailed OpenClaw configuration guide
- **WEBHOOK_SETUP.md**: Complete webhook setup instructions

## Usage Examples

### Basic Bot Setup

```bash
# Run the setup wizard
python3 telegram-bot-manager/scripts/setup_bot.py

# Follow the prompts to enter your bot token
# The script will configure OpenClaw automatically
```

### Testing Connectivity

```bash
# Test with environment variable
export TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
python3 telegram-bot-manager/scripts/test_bot.py

# Or pass token directly
python3 telegram-bot-manager/scripts/test_bot.py "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
```

### Manual Configuration

Edit your OpenClaw config:

```json
{
  "telegram": {
    "enabled": true,
    "token": "YOUR_BOT_TOKEN",
    "pairing": true,
    "streamMode": "partial"
  }
}
```

Then restart:

```bash
openclaw gateway restart
```

## Troubleshooting

### Network Issues

If you can't access api.telegram.org:

```bash
# Test connectivity
curl -I https://api.telegram.org

# Check DNS
nslookup api.telegram.org

# Test with timeout
curl -I -m 10 https://api.telegram.org
```

See [WEBHOOK_SETUP.md](references/WEBHOOK_SETUP.md) for network troubleshooting.

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
   - Use environment variables
   - Store in secure config files

2. **Use different tokens for different environments**
   - Development: `@your_bot_dev`
   - Production: `@your_bot_prod`

3. **Regular token rotation**
   - Rotate tokens every 3-6 months
   - Revoke immediately if compromised

4. **Monitor bot activity**
   - Check logs for unusual patterns
   - Review bot usage statistics

## Webhook vs Polling

### Polling (Default)
- Simpler setup
- Good for development
- No public endpoint needed

### Webhook (Production)
- More efficient
- Requires public HTTPS
- Better for high-volume bots

See [WEBHOOK_SETUP.md](references/WEBHOOK_SETUP.md) for webhook configuration.

## Bot Commands Reference

Common commands for BotFather:

- `/newbot` - Create new bot
- `/mybots` - Manage your bots
- `/token` - Get new token
- `/revoke` - Revoke current token
- `/setdescription` - Set bot description
- `/setcommands` - Set bot commands

## Testing

### Manual Testing
1. Search for your bot in Telegram
2. Send `/start` to begin conversation
3. Test basic commands

### Automated Testing
```bash
python3 telegram-bot-manager/scripts/test_bot.py
```

## Publishing to ClawHub

To publish this skill to ClawHub:

```bash
# Package the skill
python3 telegram-bot-manager/scripts/package_skill.py ./telegram-bot-manager

# Login to ClawHub
clawhub login

# Publish
clawhub publish ./telegram-bot-manager \
  --slug telegram-bot-manager \
  --name "Telegram Bot Manager" \
  --version 1.0.0 \
  --changelog "Initial release"
```

## Requirements

- OpenClaw Gateway running
- Telegram Bot Token from BotFather
- Network access to api.telegram.org
- Python 3.6+ (for scripts)

## License

This skill is provided as-is for use with OpenClaw.

## Support

For issues and questions:
- Check the references folder for detailed guides
- Review Telegram Bot API documentation
- Consult OpenClaw documentation
