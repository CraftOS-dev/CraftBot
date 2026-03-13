# -*- coding: utf-8 -*-
"""
Root config for base agent, should be overwrite by specialise agent
"""

import sys
from pathlib import Path

def get_project_root() -> Path:
    """Get the project root directory"""
    if getattr(sys, 'frozen', False):
        # Frozen exe: use CWD so logs/workspace persist (not the temp _MEIPASS dir)
        return Path.cwd()
    return Path(__file__).resolve().parent.parent

PROJECT_ROOT = get_project_root()
AGENT_WORKSPACE_ROOT = PROJECT_ROOT / "agent_file_system/workspace"
AGENT_FILE_SYSTEM_PATH = PROJECT_ROOT / "agent_file_system"
APP_DATA_PATH = PROJECT_ROOT / "app" / "data"
APP_CONFIG_PATH = PROJECT_ROOT / "app" / "config"
AGENT_FILE_SYSTEM_TEMPLATE_PATH = APP_DATA_PATH / "agent_file_system_template"
AGENT_MEMORY_CHROMA_PATH = PROJECT_ROOT / "chroma_db_memory"
SETTINGS_CONFIG_PATH = APP_CONFIG_PATH / "settings.json"
MAX_ACTIONS_PER_TASK: int = 500
MAX_TOKEN_PER_TASK: int = 12000000 # of tokens

# Memory processing configuration
PROCESS_MEMORY_AT_STARTUP: bool = False  # Process EVENT_UNPROCESSED.md into MEMORY.md at startup
MEMORY_PROCESSING_SCHEDULE_HOUR: int = 3  # Hour (0-23) to run daily memory processing

# Credential storage mode (local-only in CraftBot)
USE_REMOTE_CREDENTIALS: bool = False

# OAuth client credentials
# Uses embedded credentials with environment variable override
# See core/credentials/embedded_credentials.py for credential management
import os
from agent_core import get_credential

# Google (PKCE - only client_id required, secret kept for backwards compatibility)
GOOGLE_CLIENT_ID: str = get_credential("google", "client_id", "GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# LinkedIn (requires both client_id and client_secret)
LINKEDIN_CLIENT_ID: str = get_credential("linkedin", "client_id", "LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET: str = get_credential("linkedin", "client_secret", "LINKEDIN_CLIENT_SECRET")

# Outlook / Microsoft (PKCE - only client_id required)
OUTLOOK_CLIENT_ID: str = get_credential("outlook", "client_id", "OUTLOOK_CLIENT_ID")

# Slack (requires both client_id and client_secret - no PKCE support)
SLACK_SHARED_CLIENT_ID: str = get_credential("slack", "client_id", "SLACK_SHARED_CLIENT_ID")
SLACK_SHARED_CLIENT_SECRET: str = get_credential("slack", "client_secret", "SLACK_SHARED_CLIENT_SECRET")

# Telegram (token-based, not OAuth)
TELEGRAM_SHARED_BOT_TOKEN: str = os.environ.get("TELEGRAM_SHARED_BOT_TOKEN", "")
TELEGRAM_SHARED_BOT_USERNAME: str = os.environ.get("TELEGRAM_SHARED_BOT_USERNAME", "")

# Telegram API credentials for MTProto user login (from https://my.telegram.org)
TELEGRAM_API_ID: str = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH: str = os.environ.get("TELEGRAM_API_HASH", "")

# Notion (requires both client_id and client_secret - no PKCE support)
NOTION_SHARED_CLIENT_ID: str = get_credential("notion", "client_id", "NOTION_SHARED_CLIENT_ID")
NOTION_SHARED_CLIENT_SECRET: str = get_credential("notion", "client_secret", "NOTION_SHARED_CLIENT_SECRET")