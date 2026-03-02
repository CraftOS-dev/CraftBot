---
name: tesla
description: Control your Tesla vehicles - lock/unlock, climate, location, charge status, and more. Supports multiple vehicles.
homepage: https://tesla-api.timdorr.com
user-invocable: true
disable-model-invocation: true
metadata:
  clawdbot:
    emoji: "ðŸš—"
    primaryEnv: TESLA_EMAIL
    requires:
      bins: [python3]
      env: [TESLA_EMAIL]
---

# Tesla

Control your Tesla vehicles from Openclaw. Supports multiple cars on one account.

## Setup

[INSTALLATION AND USE INSTRUCTIONS](https://claude.ai/public/artifacts/8b737407-c689-4d2c-ba95-aad6bc49992b)

### First-time authentication:

```bash
TESLA_EMAIL="you@email.com" python3 {baseDir}/scripts/tesla.py auth
```

This will:
1. Display a Tesla login URL
2. You log in and authorize in browser
3. Paste the callback URL back
4. Token cached for future use (~30 days, auto-refreshes)

### Environment variables:

- `TESLA_EMAIL` â€” Your Tesla account email
- Token cached in `~/.tesla_cache.json`

## Multi-Vehicle Support

Use `--car` or `-c` to specify which vehicle:

```bash
# List all vehicles
python3 {baseDir}/scripts/tesla.py list

# Commands for specific car
python3 {baseDir}/scripts/tesla.py --car "Snowflake" status
python3 {baseDir}/scripts/tesla.py -c "Stella" lock
```

Without `--car`, commands target your first vehicle.

## Commands

```bash
# List all vehicles
python3 {baseDir}/scripts/tesla.py list

# Get vehicle status
python3 {baseDir}/scripts/tesla.py status
python3 {baseDir}/scripts/tesla.py --car "Stella" status

# Lock/unlock
python3 {baseDir}/scripts/tesla.py lock
python3 {baseDir}/scripts/tesla.py unlock

# Climate
python3 {baseDir}/scripts/tesla.py climate on
python3 {baseDir}/scripts/tesla.py climate off
python3 {baseDir}/scripts/tesla.py climate temp 72

# Charging
python3 {baseDir}/scripts/tesla.py charge status
python3 {baseDir}/scripts/tesla.py charge start
python3 {baseDir}/scripts/tesla.py charge stop

# Location
python3 {baseDir}/scripts/tesla.py location

# Honk & flash
python3 {baseDir}/scripts/tesla.py honk
python3 {baseDir}/scripts/tesla.py flash

# Wake up (if asleep)
python3 {baseDir}/scripts/tesla.py wake
```

## Example Chat Usage

- "Is my Tesla locked?"
- "Lock Stella"
- "What's Snowflake's battery level?"
- "Where's my Model X?"
- "Turn on the AC in Stella"
- "Honk the horn on Snowflake"

## API Reference

Uses the unofficial Tesla Owner API documented at:
https://tesla-api.timdorr.com

## Troubleshooting

**Auth not working?**
- Try opening the auth URL on your **phone browser** instead of desktop
- Make sure you're logged into the correct Tesla account
- Clear cookies and try again

## Security & Permissions

**This skill controls physical vehicles. Use with caution.**

**What this skill does:**
- Authenticates via Tesla's official OAuth flow using the `teslapy` library
- Sends vehicle commands (lock, unlock, climate, charge) to Tesla's official API
- Caches OAuth refresh token locally in `~/.tesla_cache.json`
- All communication is between your machine and Tesla's servers only

**What this skill does NOT do:**
- Does not store your Tesla password â€” uses OAuth token flow
- Does not send credentials or vehicle data to any third party
- Does not access any system resources beyond the Tesla API
- Cannot be invoked autonomously by the agent (`disable-model-invocation: true`)
- The agent must be explicitly triggered by you for every command

**Key safety:**
- Refresh token cached in `~/.tesla_cache.json` with restricted permissions
- Tokens auto-refresh for ~30 days
- Only use on trusted, personal machines
- Review `scripts/tesla.py` before first use â€” it communicates only with Tesla's official API
