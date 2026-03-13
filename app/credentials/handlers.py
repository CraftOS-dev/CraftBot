"""All integration credential handlers + registry."""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
import webbrowser
from abc import ABC, abstractmethod
from typing import Tuple
from urllib.parse import urlencode

from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "local"
REDIRECT_URI = "http://localhost:8765"
REDIRECT_URI_HTTPS = "https://localhost:8765"  # For providers that require HTTPS (e.g. Slack)

# Pending Telegram MTProto auth state: {phone_number: {phone_code_hash, session_string, api_id, api_hash}}
_pending_telegram_auth: dict[str, dict] = {}


class IntegrationHandler(ABC):
    @abstractmethod
    async def login(self, args: list[str]) -> Tuple[bool, str]: ...
    @abstractmethod
    async def logout(self, args: list[str]) -> Tuple[bool, str]: ...
    @abstractmethod
    async def status(self) -> Tuple[bool, str]: ...

    async def invite(self, args: list[str]) -> Tuple[bool, str]:
        return False, "Invite not available for this integration. Use 'login' instead."

    @property
    def subcommands(self) -> list[str]:
        return ["login", "logout", "status"]

    async def handle(self, sub: str, args: list[str]) -> Tuple[bool, str]:
        """Route subcommand. Override in subclasses for extra subcommands."""
        if sub == "invite":    return await self.invite(args)
        if sub == "login":     return await self.login(args)
        if sub == "logout":    return await self.logout(args)
        if sub == "status":    return await self.status()
        return False, f"Unknown subcommand: {sub}. Use: {', '.join(self.subcommands)}"


# ═══════════════════════════════════════════════════════════════════
# Google
# ═══════════════════════════════════════════════════════════════════

class GoogleHandler(IntegrationHandler):
    SCOPES = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"

    async def login(self, args):
        from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        if not GOOGLE_CLIENT_ID:
            return False, "Not configured. Set GOOGLE_CLIENT_ID env var (or use embedded credentials)."

        # Generate PKCE code_verifier and code_challenge (RFC 7636)
        code_verifier = secrets.token_urlsafe(64)[:128]
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip("=")

        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": self.SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        from agent_core import run_oauth_flow
        code, error = run_oauth_flow(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")
        if error: return False, f"Google OAuth failed: {error}"

        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        if GOOGLE_CLIENT_SECRET:
            token_data["client_secret"] = GOOGLE_CLIENT_SECRET

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post("https://oauth2.googleapis.com/token", data=token_data) as r:
                if r.status != 200: return False, f"Token exchange failed: {await r.text()}"
                tokens = await r.json()
            async with s.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}) as r:
                if r.status != 200: return False, "Failed to fetch user info."
                info = await r.json()

        from app.external_comms.platforms.google_workspace import GoogleCredential
        save_credential("google.json", GoogleCredential(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            token_expiry=time.time() + tokens.get("expires_in", 3600),
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            email=info.get("email", ""),
        ))
        return True, f"Google connected as {info.get('email')}"

    async def logout(self, args):
        if not has_credential("google.json"):
            return False, "No Google credentials found."
        remove_credential("google.json")
        return True, "Removed Google credential."

    async def status(self):
        if not has_credential("google.json"):
            return True, "Google: Not connected"
        from app.external_comms.platforms.google_workspace import GoogleCredential
        cred = load_credential("google.json", GoogleCredential)
        email = cred.email if cred else "unknown"
        return True, f"Google: Connected\n  - {email}"


# ═══════════════════════════════════════════════════════════════════
# Slack
# ═══════════════════════════════════════════════════════════════════

class SlackHandler(IntegrationHandler):
    @property
    def subcommands(self) -> list[str]:
        return ["invite", "login", "logout", "status"]

    async def invite(self, args):
        from app.config import SLACK_SHARED_CLIENT_ID, SLACK_SHARED_CLIENT_SECRET
        if not SLACK_SHARED_CLIENT_ID or not SLACK_SHARED_CLIENT_SECRET:
            return False, "CraftOS Slack app not configured. Set SLACK_SHARED_CLIENT_ID and SLACK_SHARED_CLIENT_SECRET env vars.\nAlternatively, use /slack login <bot_token> with your own Slack app."

        scopes = "chat:write,channels:read,channels:history,groups:read,groups:history,users:read,files:write,im:read,im:write,im:history"
        params = {"client_id": SLACK_SHARED_CLIENT_ID, "scope": scopes, "redirect_uri": REDIRECT_URI_HTTPS, "state": secrets.token_urlsafe(32)}
        from agent_core import run_oauth_flow
        code, error = run_oauth_flow(f"https://slack.com/oauth/v2/authorize?{urlencode(params)}", use_https=True)
        if error: return False, f"Slack OAuth failed: {error}"

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post("https://slack.com/api/oauth.v2.access", data={"code": code, "client_id": SLACK_SHARED_CLIENT_ID, "client_secret": SLACK_SHARED_CLIENT_SECRET, "redirect_uri": REDIRECT_URI_HTTPS}) as r:
                data = await r.json()
                if not data.get("ok"): return False, f"Slack OAuth token exchange failed: {data.get('error')}"

        bot_token = data.get("access_token", "")
        team_id = data.get("team", {}).get("id", "")
        team_name = data.get("team", {}).get("name", team_id)

        from app.external_comms.platforms.slack import SlackCredential
        save_credential("slack.json", SlackCredential(bot_token=bot_token, workspace_id=team_id, team_name=team_name))
        return True, f"Slack connected via CraftOS app: {team_name} ({team_id})"

    async def login(self, args):
        if not args: return False, "Usage: /slack login <bot_token> [workspace_name]"
        bot_token = args[0]
        if not bot_token.startswith(("xoxb-", "xoxp-")): return False, "Invalid token. Expected xoxb-... or xoxp-..."

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post("https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {bot_token}"}) as r:
                data = await r.json()
                if not data.get("ok"): return False, f"Slack auth failed: {data.get('error')}"
                team_id = data.get("team_id", "")
                workspace_name = args[1] if len(args) > 1 else data.get("team", team_id)

        from app.external_comms.platforms.slack import SlackCredential
        save_credential("slack.json", SlackCredential(bot_token=bot_token, workspace_id=team_id, team_name=workspace_name))
        return True, f"Slack connected: {workspace_name} ({team_id})"

    async def logout(self, args):
        if not has_credential("slack.json"):
            return False, "No Slack credentials found."
        remove_credential("slack.json")
        return True, "Removed Slack credential."

    async def status(self):
        if not has_credential("slack.json"):
            return True, "Slack: Not connected"
        from app.external_comms.platforms.slack import SlackCredential
        cred = load_credential("slack.json", SlackCredential)
        name = cred.team_name or cred.workspace_id if cred else "unknown"
        return True, f"Slack: Connected\n  - {name} ({cred.workspace_id})"


# ═══════════════════════════════════════════════════════════════════
# Notion
# ═══════════════════════════════════════════════════════════════════

class NotionHandler(IntegrationHandler):
    @property
    def subcommands(self) -> list[str]:
        return ["invite", "login", "logout", "status"]

    async def invite(self, args):
        from app.config import NOTION_SHARED_CLIENT_ID, NOTION_SHARED_CLIENT_SECRET
        if not NOTION_SHARED_CLIENT_ID or not NOTION_SHARED_CLIENT_SECRET:
            return False, "CraftOS Notion integration not configured. Set NOTION_SHARED_CLIENT_ID and NOTION_SHARED_CLIENT_SECRET env vars.\nAlternatively, use /notion login <token> with your own integration token."

        params = {"client_id": NOTION_SHARED_CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code", "owner": "user", "state": secrets.token_urlsafe(32)}
        from agent_core import run_oauth_flow
        code, error = run_oauth_flow(f"https://api.notion.com/v1/oauth/authorize?{urlencode(params)}")
        if error: return False, f"Notion OAuth failed: {error}"

        import aiohttp
        basic = base64.b64encode(f"{NOTION_SHARED_CLIENT_ID}:{NOTION_SHARED_CLIENT_SECRET}".encode()).decode()
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.notion.com/v1/oauth/token",
                              json={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
                              headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"}) as r:
                if r.status != 200: return False, f"Notion token exchange failed: {await r.text()}"
                data = await r.json()

        token = data.get("access_token", "")
        ws_name = data.get("workspace_name", "default")

        from app.external_comms.platforms.notion import NotionCredential
        save_credential("notion.json", NotionCredential(token=token))
        return True, f"Notion connected via CraftOS integration: {ws_name}"

    async def login(self, args):
        if not args: return False, "Usage: /notion login <integration_token>"
        token = args[0]

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.notion.com/v1/users/me", headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"}) as r:
                if r.status != 200: return False, f"Notion auth failed: {r.status}"
                data = await r.json()

        ws_name = data.get("bot", {}).get("workspace_name", "default")
        from app.external_comms.platforms.notion import NotionCredential
        save_credential("notion.json", NotionCredential(token=token))
        return True, f"Notion connected: {ws_name}"

    async def logout(self, args):
        if not has_credential("notion.json"):
            return False, "No Notion credentials found."
        remove_credential("notion.json")
        return True, "Removed Notion credential."

    async def status(self):
        if not has_credential("notion.json"):
            return True, "Notion: Not connected"
        return True, "Notion: Connected"


# ═══════════════════════════════════════════════════════════════════
# LinkedIn
# ═══════════════════════════════════════════════════════════════════

class LinkedInHandler(IntegrationHandler):
    async def login(self, args):
        from app.config import LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
        if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET:
            return False, "Not configured. Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET env vars."

        params = {"response_type": "code", "client_id": LINKEDIN_CLIENT_ID, "redirect_uri": REDIRECT_URI, "scope": "openid profile email w_member_social", "state": secrets.token_urlsafe(32)}
        from agent_core import run_oauth_flow
        code, error = run_oauth_flow(f"https://www.linkedin.com/oauth/v2/authorization?{urlencode(params)}")
        if error: return False, f"LinkedIn OAuth failed: {error}"

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post("https://www.linkedin.com/oauth/v2/accessToken", data={"grant_type": "authorization_code", "code": code, "client_id": LINKEDIN_CLIENT_ID, "client_secret": LINKEDIN_CLIENT_SECRET, "redirect_uri": REDIRECT_URI}) as r:
                if r.status != 200: return False, f"Token exchange failed: {await r.text()}"
                tokens = await r.json()
            async with s.get("https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}) as r:
                if r.status != 200: return False, "Failed to fetch user info."
                info = await r.json()

        from app.external_comms.platforms.linkedin import LinkedInCredential
        save_credential("linkedin.json", LinkedInCredential(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            token_expiry=time.time() + tokens.get("expires_in", 3600),
            client_id=LINKEDIN_CLIENT_ID,
            client_secret=LINKEDIN_CLIENT_SECRET,
            linkedin_id=info.get("sub", ""),
            user_id=info.get("sub", ""),
        ))
        return True, f"LinkedIn connected as {info.get('name')} ({info.get('email')})"

    async def logout(self, args):
        if not has_credential("linkedin.json"):
            return False, "No LinkedIn credentials found."
        remove_credential("linkedin.json")
        return True, "Removed LinkedIn credential."

    async def status(self):
        if not has_credential("linkedin.json"):
            return True, "LinkedIn: Not connected"
        from app.external_comms.platforms.linkedin import LinkedInCredential
        cred = load_credential("linkedin.json", LinkedInCredential)
        lid = cred.linkedin_id if cred else "unknown"
        return True, f"LinkedIn: Connected\n  - {lid}"



# ═══════════════════════════════════════════════════════════════════
# Discord (bot token)
# ═══════════════════════════════════════════════════════════════════

class DiscordHandler(IntegrationHandler):
    @property
    def subcommands(self) -> list[str]:
        return ["login", "logout", "status"]

    async def login(self, args):
        if not args: return False, "Usage: /discord login <bot_token>"
        bot_token = args[0]

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bot {bot_token}"}) as r:
                if r.status != 200: return False, f"Invalid bot token: {r.status}"
                data = await r.json()

        from app.external_comms.platforms.discord import DiscordCredential
        save_credential("discord.json", DiscordCredential(bot_token=bot_token))
        return True, f"Discord bot connected: {data.get('username')} ({data.get('id')})"

    async def logout(self, args):
        if not has_credential("discord.json"):
            return False, "No Discord credentials found."
        # Stop the active gateway listener before removing credentials
        try:
            from app.external_comms.manager import get_external_comms_manager
            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform("discord")
        except Exception:
            pass
        remove_credential("discord.json")
        return True, "Removed Discord credential."

    async def status(self):
        if not has_credential("discord.json"):
            return True, "Discord: Not connected"
        from app.external_comms.platforms.discord import DiscordCredential
        cred = load_credential("discord.json", DiscordCredential)
        if not cred or not cred.bot_token:
            return True, "Discord: Not connected"
        return True, "Discord: Connected (bot token)"


# ═══════════════════════════════════════════════════════════════════
# Telegram (unified: invite + bot + user)
# ═══════════════════════════════════════════════════════════════════

class TelegramHandler(IntegrationHandler):
    @property
    def subcommands(self) -> list[str]:
        return ["invite", "login", "login-user", "login-qr", "logout", "status"]

    async def handle(self, sub, args):
        if sub == "login-user": return await self._login_user(args)
        if sub == "login-qr": return await self._login_qr(args)
        return await super().handle(sub, args)

    async def invite(self, args):
        from app.config import TELEGRAM_SHARED_BOT_TOKEN, TELEGRAM_SHARED_BOT_USERNAME
        if not TELEGRAM_SHARED_BOT_TOKEN or not TELEGRAM_SHARED_BOT_USERNAME:
            return False, "CraftOS Telegram bot not configured. Set TELEGRAM_SHARED_BOT_TOKEN and TELEGRAM_SHARED_BOT_USERNAME env vars.\nAlternatively, use /telegram login <bot_token> with your own bot from @BotFather."

        # Validate shared bot token
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{TELEGRAM_SHARED_BOT_TOKEN}/getMe") as r:
                data = await r.json()
                if not data.get("ok"): return False, f"CraftOS Telegram bot token is invalid: {data.get('description')}"
                info = data["result"]

        from app.external_comms.platforms.telegram_bot import TelegramBotCredential
        save_credential("telegram_bot.json", TelegramBotCredential(
            bot_token=TELEGRAM_SHARED_BOT_TOKEN,
            bot_username=info.get("username", ""),
        ))

        bot_link = f"https://t.me/{TELEGRAM_SHARED_BOT_USERNAME}"
        webbrowser.open(bot_link)
        return True, (
            f"CraftOS Telegram bot connected: @{info.get('username')}\n"
            f"Start chatting or add to groups: {bot_link}"
        )

    async def login(self, args):
        if not args: return False, "Usage: /telegram login <bot_token>\nGet from @BotFather on Telegram."
        bot_token = args[0]

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.telegram.org/bot{bot_token}/getMe") as r:
                data = await r.json()
                if not data.get("ok"): return False, f"Invalid bot token: {data.get('description')}"
                info = data["result"]

        from app.external_comms.platforms.telegram_bot import TelegramBotCredential
        save_credential("telegram_bot.json", TelegramBotCredential(
            bot_token=bot_token,
            bot_username=info.get("username", ""),
        ))
        return True, f"Telegram bot connected: @{info.get('username')} ({info.get('id')})"

    async def _login_user(self, args):
        if not args:
            return False, (
                "Usage:\n"
                "  Step 1: /telegram login-user <phone_number>\n"
                "  Step 2: /telegram login-user <phone_number> <code> [2fa_password]\n\n"
                "Requires TELEGRAM_API_ID and TELEGRAM_API_HASH env vars.\n"
                "Get them from https://my.telegram.org"
            )

        phone = args[0]

        from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            return False, (
                "Not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH env vars.\n"
                "Get them from https://my.telegram.org → API development tools."
            )

        try:
            api_id = int(TELEGRAM_API_ID)
        except ValueError:
            return False, "TELEGRAM_API_ID must be a number."

        # Step 2: phone + code → complete auth
        if len(args) >= 2:
            code = args[1]
            password = args[2] if len(args) > 2 else None

            pending = _pending_telegram_auth.get(phone)
            if not pending:
                return False, f"No pending auth for {phone}. Run /telegram login-user {phone} first to send the code."

            try:
                from app.external_comms.platforms.telegram_mtproto_helpers import complete_auth
            except ImportError:
                return False, "Telethon not installed. Run: pip install telethon"

            result = await complete_auth(
                api_id=api_id,
                api_hash=TELEGRAM_API_HASH,
                phone_number=phone,
                code=code,
                phone_code_hash=pending["phone_code_hash"],
                password=password,
                pending_session_string=pending["session_string"],
            )

            if "error" in result:
                details = result.get("details", {})
                if details.get("status") == "2fa_required":
                    return False, "Two-factor authentication is enabled.\nUsage: /telegram login-user <phone> <code> <2fa_password>"
                if details.get("status") == "invalid_code":
                    return False, "Invalid verification code. Try again with: /telegram login-user <phone> <code>"
                if details.get("status") == "code_expired":
                    _pending_telegram_auth.pop(phone, None)
                    return False, "Code expired. Run /telegram login-user <phone> again to get a new code."
                return False, f"Auth failed: {result['error']}"

            # Success — store credential
            auth = result["result"]
            _pending_telegram_auth.pop(phone, None)

            from app.external_comms.platforms.telegram_user import TelegramUserCredential
            save_credential("telegram_user.json", TelegramUserCredential(
                session_string=auth["session_string"],
                api_id=str(api_id),
                api_hash=TELEGRAM_API_HASH,
                phone_number=auth.get("phone", phone),
            ))

            account_name = f"{auth.get('first_name', '')} {auth.get('last_name', '')}".strip()
            username = f" (@{auth['username']})" if auth.get("username") else ""
            return True, f"Telegram user connected: {account_name}{username}"

        # Step 1: phone only → send OTP
        try:
            from app.external_comms.platforms.telegram_mtproto_helpers import start_auth
        except ImportError:
            return False, "Telethon not installed. Run: pip install telethon"

        result = await start_auth(api_id=api_id, api_hash=TELEGRAM_API_HASH, phone_number=phone)

        if "error" in result:
            return False, f"Failed to send code: {result['error']}"

        # Store pending auth state
        _pending_telegram_auth[phone] = {
            "phone_code_hash": result["result"]["phone_code_hash"],
            "session_string": result["result"]["session_string"],
        }

        return True, (
            f"Verification code sent to {phone}.\n"
            f"Check your Telegram app (or SMS) for the code, then run:\n"
            f"  /telegram login-user {phone} <code>"
        )

    async def _login_qr(self, args):
        """Login to Telegram user account by scanning a QR code."""
        logger.info("[Telegram QR] Starting QR login flow")
        from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            logger.warning("[Telegram QR] Missing TELEGRAM_API_ID or TELEGRAM_API_HASH env vars")
            return False, (
                "Not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH env vars.\n"
                "Get them from https://my.telegram.org → API development tools."
            )

        try:
            api_id = int(TELEGRAM_API_ID)
        except ValueError:
            return False, "TELEGRAM_API_ID must be a number."

        try:
            from app.external_comms.platforms.telegram_mtproto_helpers import qr_login
        except ImportError:
            logger.error("[Telegram QR] Telethon not installed")
            return False, "Telethon not installed. Run: pip install telethon"

        # Verify qrcode package is available before starting the flow
        try:
            import qrcode as _qrcode_check  # noqa: F401
        except ImportError:
            logger.error("[Telegram QR] qrcode package not installed")
            return False, "qrcode package not installed. Run: pip install qrcode[pil]"

        import tempfile, os

        qr_file_path = None
        qr_error = None

        def on_qr_url(url: str):
            """Generate QR code image and open it for the user to scan."""
            nonlocal qr_file_path, qr_error
            try:
                import qrcode
                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")

                qr_file_path = os.path.join(tempfile.gettempdir(), "telegram_qr_login.png")
                img.save(qr_file_path)
                logger.info(f"[Telegram QR] QR code saved to {qr_file_path}")

                # Open the QR code image (prefer os.startfile on Windows)
                import sys
                if sys.platform == "win32":
                    os.startfile(qr_file_path)
                else:
                    webbrowser.open(f"file://{qr_file_path}")
                logger.info("[Telegram QR] QR code opened")
            except Exception as e:
                qr_error = str(e)
                logger.error(f"[Telegram QR] Failed to generate/open QR code: {e}")

        logger.info("[Telegram QR] Calling qr_login...")
        result = await qr_login(
            api_id=api_id,
            api_hash=TELEGRAM_API_HASH,
            on_qr_url=on_qr_url,
            timeout=120,
        )
        logger.info(f"[Telegram QR] qr_login returned: {'ok' if 'ok' in result else 'error'}")

        # Clean up QR image
        if qr_file_path and os.path.exists(qr_file_path):
            try:
                os.remove(qr_file_path)
            except Exception:
                pass

        if "error" in result:
            details = result.get("details", {})
            if details.get("status") == "2fa_required":
                # Save pending session for 2FA completion
                session_str = details.get("session_string", "")
                if session_str:
                    _pending_telegram_auth["__qr_2fa__"] = {"session_string": session_str}
                return False, (
                    "QR scan succeeded but 2FA is enabled.\n"
                    "Complete login with: /telegram login-user <phone> <code> <2fa_password>\n"
                    "Or disable 2FA in Telegram settings and try again."
                )
            return False, f"QR login failed: {result['error']}"

        # Success — store credential
        auth = result["result"]
        from app.external_comms.platforms.telegram_user import TelegramUserCredential
        save_credential("telegram_user.json", TelegramUserCredential(
            session_string=auth["session_string"],
            api_id=str(api_id),
            api_hash=TELEGRAM_API_HASH,
            phone_number=auth.get("phone", ""),
        ))

        account_name = f"{auth.get('first_name', '')} {auth.get('last_name', '')}".strip()
        username = f" (@{auth['username']})" if auth.get("username") else ""
        return True, f"Telegram user linked: {account_name}{username}"

    async def logout(self, args):
        bot_exists = has_credential("telegram_bot.json")
        user_exists = has_credential("telegram_user.json")

        if not bot_exists and not user_exists:
            return False, "No Telegram credentials found."

        if args:
            target = args[0].lower()
            if target in ("bot", "bot_api"):
                if bot_exists:
                    remove_credential("telegram_bot.json")
                    return True, "Removed Telegram bot credential."
                return False, "No Telegram bot credential found."
            elif target in ("user", "mtproto"):
                if user_exists:
                    remove_credential("telegram_user.json")
                    return True, "Removed Telegram user credential."
                return False, "No Telegram user credential found."
            elif target == "all":
                if bot_exists: remove_credential("telegram_bot.json")
                if user_exists: remove_credential("telegram_user.json")
                return True, "Removed all Telegram credentials."
            else:
                return False, f"Unknown Telegram credential target: {target}. Use 'bot' or 'user'."

        # No args — remove all
        if bot_exists: remove_credential("telegram_bot.json")
        if user_exists: remove_credential("telegram_user.json")
        return True, "Removed all Telegram credentials."

    async def status(self):
        bot_exists = has_credential("telegram_bot.json")
        user_exists = has_credential("telegram_user.json")

        if not bot_exists and not user_exists:
            return True, "Telegram: Not connected"

        lines = []
        if bot_exists:
            from app.external_comms.platforms.telegram_bot import TelegramBotCredential
            cred = load_credential("telegram_bot.json", TelegramBotCredential)
            bot_label = f"@{cred.bot_username}" if cred and cred.bot_username else "Bot configured"
            lines.append(f"  - {bot_label} (bot)")
        if user_exists:
            from app.external_comms.platforms.telegram_user import TelegramUserCredential
            cred = load_credential("telegram_user.json", TelegramUserCredential)
            user_label = cred.phone_number if cred and cred.phone_number else "User configured"
            lines.append(f"  - {user_label} (user)")

        return True, "Telegram: Connected\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# WhatsApp (unified: business + web)
# ═══════════════════════════════════════════════════════════════════

class WhatsAppHandler(IntegrationHandler):
    @property
    def subcommands(self) -> list[str]:
        return ["login", "logout", "status"]

    async def handle(self, sub, args):
        if sub == "login": return await self._login_web(args)
        return await super().handle(sub, args)

    async def login(self, args):
        return await self._login_web(args)

    async def _login_web(self, args):
        import asyncio

        try:
            from app.external_comms.platforms.whatsapp_bridge.client import get_whatsapp_bridge
        except ImportError:
            return False, "WhatsApp bridge not available. Ensure Node.js >= 18 is installed."

        bridge = get_whatsapp_bridge()

        # Start bridge if not already running
        if not bridge.is_running:
            try:
                await bridge.start()
            except Exception as e:
                return False, f"Failed to start WhatsApp bridge: {e}"

        # Wait for either QR code or ready (already authenticated)
        event_type, event_data = await bridge.wait_for_qr_or_ready(timeout=60.0)

        if event_type == "ready":
            # Already authenticated — save credential and stop the bridge
            # (start_listening will restart it on the main event loop)
            from app.external_comms.platforms.whatsapp_web import WhatsAppWebCredential
            owner_phone = bridge.owner_phone or ""
            owner_name = bridge.owner_name or ""
            save_credential("whatsapp_web.json", WhatsAppWebCredential(
                session_id="bridge",
                owner_phone=owner_phone,
                owner_name=owner_name,
            ))
            await bridge.stop()
            display = owner_phone or owner_name or "connected"
            return True, f"WhatsApp Web connected: +{display}"

        if event_type == "qr":
            # Show QR code to user — try terminal first, then image fallback
            qr_string = (event_data or {}).get("qr_string", "")
            if qr_string:
                try:
                    import qrcode, sys
                    qr = qrcode.QRCode(border=1)
                    qr.add_data(qr_string)
                    qr.make(fit=True)
                    matrix = qr.get_matrix()
                    lines = []
                    for row in matrix:
                        lines.append("".join("##" if cell else "  " for cell in row))
                    qr_text = "\n".join(lines)
                    sys.stderr.write(f"\n{qr_text}\n\n")
                    sys.stderr.write("Scan the QR code above with WhatsApp on your phone\n\n")
                    sys.stderr.flush()
                    logger.info("[WhatsApp] QR code printed to terminal")
                except Exception as e:
                    logger.debug(f"[WhatsApp] Could not print QR to terminal: {e}")

            # Also try opening as image in browser
            qr_data_url = (event_data or {}).get("qr_data_url")
            if qr_data_url:
                import tempfile, base64 as b64, os
                qr_b64 = qr_data_url
                if qr_b64.startswith("data:image"):
                    qr_b64 = qr_b64.split(",", 1)[1]
                qr_path = os.path.join(tempfile.gettempdir(), "whatsapp_qr_bridge.png")
                with open(qr_path, "wb") as f:
                    f.write(b64.b64decode(qr_b64))
                webbrowser.open(f"file://{qr_path}")

            # Wait for ready after QR scan (up to 120s)
            ready = await bridge.wait_for_ready(timeout=120.0)
            if not ready:
                return False, "Timed out waiting for QR scan. Run /whatsapp login again."

            # Save credential with owner info, then stop bridge
            # (start_listening will restart it on the main event loop)
            from app.external_comms.platforms.whatsapp_web import WhatsAppWebCredential
            owner_phone = bridge.owner_phone or ""
            owner_name = bridge.owner_name or ""
            save_credential("whatsapp_web.json", WhatsAppWebCredential(
                session_id="bridge",
                owner_phone=owner_phone,
                owner_name=owner_name,
            ))
            await bridge.stop()
            display = owner_phone or owner_name or "connected"
            return True, f"WhatsApp Web connected: +{display}"

        # Timeout
        return False, "Timed out waiting for WhatsApp bridge. Run /whatsapp login again."

    async def logout(self, args):
        if not has_credential("whatsapp_web.json"):
            return False, "No WhatsApp credentials found."
        remove_credential("whatsapp_web.json")
        return True, "Removed WhatsApp credential."

    async def status(self):
        if not has_credential("whatsapp_web.json"):
            return True, "WhatsApp: Not connected"
        from app.external_comms.platforms.whatsapp_web import WhatsAppWebCredential
        cred = load_credential("whatsapp_web.json", WhatsAppWebCredential)
        if not cred:
            return True, "WhatsApp: Not connected"
        phone = cred.owner_phone or "unknown"
        name = cred.owner_name or ""
        label = f"+{phone}" + (f" ({name})" if name else "")
        return True, f"WhatsApp: Connected\n  - {label}"



# ═══════════════════════════════════════════════════════════════════
# Outlook
# ═══════════════════════════════════════════════════════════════════

class OutlookHandler(IntegrationHandler):
    SCOPES = "Mail.Read Mail.Send Mail.ReadWrite User.Read offline_access"

    async def login(self, args):
        from app.config import OUTLOOK_CLIENT_ID
        if not OUTLOOK_CLIENT_ID:
            return False, "Not configured. Set OUTLOOK_CLIENT_ID env var (or use embedded credentials)."

        # Generate PKCE code_verifier and code_challenge (RFC 7636)
        code_verifier = secrets.token_urlsafe(64)[:128]
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip("=")

        params = {
            "client_id": OUTLOOK_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": self.SCOPES,
            "response_mode": "query",
            "state": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        from agent_core import run_oauth_flow
        code, error = run_oauth_flow(
            f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urlencode(params)}"
        )
        if error:
            return False, f"Outlook OAuth failed: {error}"

        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                data={
                    "client_id": OUTLOOK_CLIENT_ID,
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                    "scope": self.SCOPES,
                },
            ) as r:
                if r.status != 200:
                    return False, f"Token exchange failed: {await r.text()}"
                tokens = await r.json()

            async with s.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            ) as r:
                if r.status != 200:
                    return False, "Failed to fetch user info."
                info = await r.json()

        user_email = info.get("mail") or info.get("userPrincipalName", "")

        from app.external_comms.platforms.outlook import OutlookCredential
        save_credential("outlook.json", OutlookCredential(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            token_expiry=time.time() + tokens.get("expires_in", 3600),
            client_id=OUTLOOK_CLIENT_ID,
            email=user_email,
        ))
        return True, f"Outlook connected as {user_email}"

    async def logout(self, args):
        if not has_credential("outlook.json"):
            return False, "No Outlook credentials found."
        remove_credential("outlook.json")
        return True, "Removed Outlook credential."

    async def status(self):
        if not has_credential("outlook.json"):
            return True, "Outlook: Not connected"
        from app.external_comms.platforms.outlook import OutlookCredential
        cred = load_credential("outlook.json", OutlookCredential)
        email = cred.email if cred else "unknown"
        return True, f"Outlook: Connected\n  - {email}"


# ═══════════════════════════════════════════════════════════════════
# WhatsApp Business
# ═══════════════════════════════════════════════════════════════════

class WhatsAppBusinessHandler(IntegrationHandler):
    async def login(self, args):
        if len(args) < 2: return False, "Usage: /whatsapp-business login <access_token> <phone_number_id>"
        access_token, phone_number_id = args[0], args[1]

        # Validate by calling the API
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://graph.facebook.com/v21.0/{phone_number_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            ) as r:
                if r.status != 200: return False, f"Invalid credentials: {r.status}"

        from app.external_comms.platforms.whatsapp_business import WhatsAppBusinessCredential
        save_credential("whatsapp_business.json", WhatsAppBusinessCredential(
            access_token=access_token, phone_number_id=phone_number_id,
        ))
        return True, f"WhatsApp Business connected (phone number ID: {phone_number_id})"

    async def logout(self, args):
        if not has_credential("whatsapp_business.json"):
            return False, "No WhatsApp Business credentials found."
        remove_credential("whatsapp_business.json")
        return True, "Removed WhatsApp Business credential."

    async def status(self):
        if not has_credential("whatsapp_business.json"):
            return True, "WhatsApp Business: Not connected"
        from app.external_comms.platforms.whatsapp_business import WhatsAppBusinessCredential
        cred = load_credential("whatsapp_business.json", WhatsAppBusinessCredential)
        pid = cred.phone_number_id if cred else "unknown"
        return True, f"WhatsApp Business: Connected\n  - Phone Number ID: {pid}"


# ═══════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════

INTEGRATION_HANDLERS: dict[str, IntegrationHandler] = {
    "google":             GoogleHandler(),
    "slack":              SlackHandler(),
    "notion":             NotionHandler(),
    "linkedin":           LinkedInHandler(),
    "discord":            DiscordHandler(),
    "telegram":           TelegramHandler(),
    "whatsapp":           WhatsAppHandler(),
    "outlook":            OutlookHandler(),
    "whatsapp_business":  WhatsAppBusinessHandler(),
}
