# -*- coding: utf-8 -*-
"""Twitter/X integration - handler + client + credential. OAuth 1.0a."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets as _secrets
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    PlatformMessage,
    has_credential,
    load_config,
    load_credential,
    save_config,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import Result, arequest, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

TWITTER_API = "https://api.twitter.com/2"
POLL_INTERVAL = 30
RETRY_DELAY = 60


@dataclass
class TwitterCredential:
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    access_token_secret: str = ""
    user_id: str = ""
    username: str = ""


@dataclass
class TwitterConfig:
    """Runtime knobs separate from the credential - persisted as
    ``twitter_config.json``."""

    watch_tag: str = ""


TWITTER = IntegrationSpec(
    name="twitter",
    cred_class=TwitterCredential,
    cred_file="twitter.json",
    platform_id="twitter",
)


def _twitter_config_file() -> str:
    """``twitter.json`` â†’ ``twitter_config.json``."""
    stem = TWITTER.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


def _oauth1_header(
    method: str,
    url: str,
    params: Dict[str, str],
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
) -> str:
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": _secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth_params}
    sorted_params = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(sorted_params, safe='')}"
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    header_parts = ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(TWITTER.name)
class TwitterHandler(IntegrationHandler):
    spec = TWITTER
    display_name = "Twitter/X"
    description = "Tweets, mentions, and timeline"
    auth_type = "token"
    icon = "twitter"
    connect_help = [
        "Open developer.twitter.com/en/portal/dashboard",
        "Sign up for a developer account if you haven't (free tier works for posting)",
        "Create a Project, then a Standalone App inside it",
        "App settings â†’ User authentication settings â†’ enable OAuth 1.0a with Read+Write",
        "Keys and tokens tab â†’ copy Consumer Key + Consumer Secret",
        "Scroll down â†’ Generate Access Token + Secret â†’ copy both",
    ]
    fields = [
        {
            "key": "api_key",
            "label": "Consumer Key",
            "placeholder": "Enter Consumer key",
            "password": True,
        },
        {
            "key": "api_secret",
            "label": "Consumer Secret",
            "placeholder": "Enter Consumer secret",
            "password": True,
        },
        {
            "key": "access_token",
            "label": "Access Token",
            "placeholder": "Enter access token",
            "password": True,
        },
        {
            "key": "access_token_secret",
            "label": "Access Token Secret",
            "placeholder": "Enter access token secret",
            "password": True,
        },
    ]
    config_class = TwitterConfig
    config_fields = [
        {
            "key": "watch_tag",
            "label": "Watch tag",
            "type": "text",
            "placeholder": "@craftbot",
            "help": "Trigger keyword in mentions. Leave empty to react to all mentions.",
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 4:
            return False, (
                "Usage: /twitter login <api_key> <api_secret> <access_token> <access_token_secret>\n"
                "Get these from developer.x.com"
            )
        api_key, api_secret, access_token, access_token_secret = (
            args[0].strip(),
            args[1].strip(),
            args[2].strip(),
            args[3].strip(),
        )

        url = "https://api.twitter.com/2/users/me"
        params = {"user.fields": "id,name,username"}
        auth_hdr = _oauth1_header(
            "GET", url, params, api_key, api_secret, access_token, access_token_secret
        )
        result = http_request(
            "GET",
            url,
            headers={"Authorization": auth_hdr},
            params=params,
            expected=(200,),
        )
        if "error" in result:
            return False, (
                f"Twitter auth failed: {result['error']}. "
                f"Check your API credentials.\nGet them from developer.x.com â†’ Dashboard â†’ Keys and tokens"
            )
        data = (result["result"] or {}).get("data", {})

        save_credential(
            self.spec.cred_file,
            TwitterCredential(
                api_key=api_key,
                api_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
                user_id=data.get("id", ""),
                username=data.get("username", ""),
            ),
        )
        return (
            True,
            f"Twitter/X connected as @{data.get('username')} ({data.get('name', '')})",
        )

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Twitter credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed Twitter credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Twitter/X: Not connected"
        cred = load_credential(self.spec.cred_file, TwitterCredential)
        if not cred:
            return True, "Twitter/X: Not connected"
        username = cred.username or "unknown"
        cfg = load_config(_twitter_config_file(), TwitterConfig) or TwitterConfig()
        tag_info = f" [tag: {cfg.watch_tag}]" if cfg.watch_tag else ""
        return True, f"Twitter/X: Connected\n  - @{username}{tag_info}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class TwitterClient(BasePlatformClient):
    spec = TWITTER
    PLATFORM_ID = TWITTER.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[TwitterCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._since_id: Optional[str] = None
        self._seen_ids: set = set()

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> TwitterCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, TwitterCredential)
        if self._cred is None:
            raise RuntimeError("No Twitter credentials. Use /twitter login first.")
        return self._cred

    def _auth_header(
        self, method: str, url: str, params: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        cred = self._load()
        return {
            "Authorization": _oauth1_header(
                method,
                url,
                params or {},
                cred.api_key,
                cred.api_secret,
                cred.access_token,
                cred.access_token_secret,
            ),
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return await self.post_tweet(text, reply_to=recipient if recipient else None)

    def _config(self) -> TwitterConfig:
        return load_config(_twitter_config_file(), TwitterConfig) or TwitterConfig()

    def get_watch_tag(self) -> str:
        return self._config().watch_tag

    def set_watch_tag(self, tag: str) -> None:
        cfg = self._config()
        cfg.watch_tag = tag.strip()
        save_config(_twitter_config_file(), cfg)

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return
        self._message_callback = callback
        cred = self._load()

        me = await self.get_me()
        if "error" in me:
            raise RuntimeError(f"Invalid Twitter credentials: {me.get('error')}")

        user_data = me.get("result", {})
        username = user_data.get("username", "unknown")
        user_id = user_data.get("id", "")

        if cred.username != username or cred.user_id != user_id:
            cred.username = username
            cred.user_id = user_id
            save_credential(self.spec.cred_file, cred)
            self._cred = cred

        self._listening = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None

    async def _poll_loop(self) -> None:
        try:
            await self._catchup()
        except Exception as e:
            logger.warning(f"[TWITTER] Catchup error: {e}")

        while self._listening:
            try:
                await self._check_mentions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TWITTER] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(POLL_INTERVAL)

    async def _catchup(self) -> None:
        cred = self._load()
        if not cred.user_id:
            return
        url = f"{TWITTER_API}/users/{cred.user_id}/mentions"
        params = {"max_results": "5", "tweet.fields": "created_at,author_id,text"}
        result = await arequest(
            "GET",
            url,
            headers=self._auth_header("GET", url, params),
            params=params,
            expected=(200,),
        )
        if "error" in result:
            return
        tweets = (result["result"] or {}).get("data", [])
        if tweets:
            self._since_id = tweets[0].get("id")
            for t in tweets:
                self._seen_ids.add(t.get("id"))

    async def _check_mentions(self) -> None:
        cred = self._load()
        if not cred.user_id:
            return
        url = f"{TWITTER_API}/users/{cred.user_id}/mentions"
        params: Dict[str, str] = {
            "max_results": "20",
            "tweet.fields": "created_at,author_id,text,in_reply_to_user_id,conversation_id",
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        if self._since_id:
            params["since_id"] = self._since_id

        result = await arequest(
            "GET",
            url,
            headers=self._auth_header("GET", url, params),
            params=params,
            expected=(200,),
        )
        if "error" in result:
            if "429" in result["error"]:
                await asyncio.sleep(60)
            else:
                logger.warning(f"[TWITTER] Mentions API {result['error']}")
            return

        data = result["result"] or {}
        tweets = data.get("data", [])
        if not tweets:
            return

        users_map = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        self._since_id = tweets[0].get("id")

        for tweet in reversed(tweets):
            tid = tweet.get("id", "")
            if tid in self._seen_ids:
                continue
            self._seen_ids.add(tid)
            await self._dispatch_mention(tweet, users_map)

        if len(self._seen_ids) > 500:
            self._seen_ids = set(list(self._seen_ids)[-200:])

    async def _dispatch_mention(
        self, tweet: Dict[str, Any], users_map: Dict[str, Any]
    ) -> None:
        if not self._message_callback:
            return

        text = tweet.get("text", "")
        author_id = tweet.get("author_id", "")
        author_info = users_map.get(author_id, {})
        author_username = author_info.get("username", "")
        author_name = author_info.get("name", author_username)

        watch_tag = self._config().watch_tag
        if watch_tag:
            if watch_tag.lower() not in text.lower():
                return
            tag_lower = watch_tag.lower()
            idx = text.lower().find(tag_lower)
            instruction = text[idx + len(watch_tag) :].strip() if idx >= 0 else text
        else:
            instruction = text

        clean_instruction = instruction
        while clean_instruction.startswith("@"):
            parts = clean_instruction.split(" ", 1)
            clean_instruction = parts[1].strip() if len(parts) > 1 else ""

        timestamp = None
        try:
            timestamp = datetime.fromisoformat(
                tweet.get("created_at", "").replace("Z", "+00:00")
            )
        except Exception:
            pass

        await self._message_callback(
            PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=author_id,
                sender_name=f"@{author_username}" if author_username else author_name,
                text=f"@{author_username}: {clean_instruction or text}",
                channel_id=tweet.get("conversation_id", ""),
                channel_name="Twitter/X",
                message_id=tweet.get("id", ""),
                timestamp=timestamp,
                raw={
                    "tweet": tweet,
                    "trigger": "mention" if not watch_tag else "mention_tag",
                    "tag": watch_tag,
                    "instruction": clean_instruction or text,
                    "author_username": author_username,
                },
            )
        )

    # ----- API methods -----

    async def get_me(self) -> Result:
        url = f"{TWITTER_API}/users/me"
        params = {"user.fields": "id,name,username,description,public_metrics"}
        return await arequest(
            "GET",
            url,
            headers=self._auth_header("GET", url, params),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", {}),
        )

    async def post_tweet(self, text: str, reply_to: Optional[str] = None) -> Result:
        url = f"{TWITTER_API}/tweets"
        payload: Dict[str, Any] = {"text": text}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        return await arequest(
            "POST",
            url,
            headers={
                **self._auth_header("POST", url),
                "Content-Type": "application/json",
            },
            json=payload,
            transform=lambda d: {
                "id": d.get("data", {}).get("id"),
                "text": d.get("data", {}).get("text"),
            },
        )

    async def delete_tweet(self, tweet_id: str) -> Result:
        url = f"{TWITTER_API}/tweets/{tweet_id}"
        return await arequest(
            "DELETE",
            url,
            headers=self._auth_header("DELETE", url),
            expected=(200,),
            transform=lambda _d: {"deleted": True},
        )

    async def get_user_timeline(
        self, user_id: Optional[str] = None, max_results: int = 10
    ) -> Result:
        cred = self._load()
        uid = user_id or cred.user_id
        if not uid:
            return {"error": "No user_id available"}
        url = f"{TWITTER_API}/users/{uid}/tweets"
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,text",
        }
        return await arequest(
            "GET",
            url,
            headers=self._auth_header("GET", url, params),
            params=params,
            expected=(200,),
        )

    async def search_tweets(self, query: str, max_results: int = 10) -> Result:
        url = f"{TWITTER_API}/tweets/search/recent"
        params = {
            "query": query,
            "max_results": str(max_results),
            "tweet.fields": "created_at,author_id,public_metrics,text",
            "expansions": "author_id",
            "user.fields": "username",
        }
        return await arequest(
            "GET",
            url,
            headers=self._auth_header("GET", url, params),
            params=params,
            expected=(200,),
        )

    async def like_tweet(self, tweet_id: str) -> Result:
        cred = self._load()
        url = f"{TWITTER_API}/users/{cred.user_id}/likes"
        return await arequest(
            "POST",
            url,
            headers={
                **self._auth_header("POST", url),
                "Content-Type": "application/json",
            },
            json={"tweet_id": tweet_id},
            expected=(200,),
            transform=lambda d: d.get("data", {}),
        )

    async def retweet(self, tweet_id: str) -> Result:
        cred = self._load()
        url = f"{TWITTER_API}/users/{cred.user_id}/retweets"
        return await arequest(
            "POST",
            url,
            headers={
                **self._auth_header("POST", url),
                "Content-Type": "application/json",
            },
            json={"tweet_id": tweet_id},
            expected=(200,),
            transform=lambda d: d.get("data", {}),
        )

    async def get_user_by_username(self, username: str) -> Result:
        url = f"{TWITTER_API}/users/by/username/{username}"
        params = {"user.fields": "id,name,username,description,public_metrics"}
        return await arequest(
            "GET",
            url,
            headers=self._auth_header("GET", url, params),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("data", {}),
        )

    async def reply_to_tweet(self, tweet_id: str, text: str) -> Result:
        return await self.post_tweet(text, reply_to=tweet_id)
