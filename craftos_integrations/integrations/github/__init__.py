# -*- coding: utf-8 -*-
"""GitHub integration — handler + client + credential.

This is the canonical example of an integration package:
  - one credential dataclass
  - one IntegrationSpec (referenced by both handler and client = composition)
  - one IntegrationHandler (auth: login/logout/status)
  - one BasePlatformClient (runtime: notification polling, REST API)

To add another integration, copy this folder and adapt.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

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

GITHUB_API = "https://api.github.com"
POLL_INTERVAL = 15
RETRY_DELAY = 30


@dataclass
class GitHubCredential:
    access_token: str = ""
    username: str = ""


@dataclass
class GitHubConfig:
    """Runtime knobs separate from the credential - loaded fresh from
    ``github_config.json`` whenever the client reads them."""

    watch_tag: str = ""
    watch_repos: List[str] = field(default_factory=list)


GITHUB = IntegrationSpec(
    name="github",
    cred_class=GitHubCredential,
    cred_file="github.json",
    platform_id="github",
)


def _github_config_file() -> str:
    """``github.json`` â†’ ``github_config.json`` - must match the convention
    in ``service._config_filename``."""
    stem = GITHUB.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# -----------------------------------------------------------------
# Handler - auth flows
# -----------------------------------------------------------------


@register_handler(GITHUB.name)
class GitHubHandler(IntegrationHandler):
    spec = GITHUB
    display_name = "GitHub"
    description = "Repositories, issues, and pull requests"
    auth_type = "token"
    icon = "github"
    connect_help = [
        "Open GitHub: github.com/settings/tokens",
        "Click 'Generate new token' â†’ 'Generate new token (classic)'",
        "Set scopes: at minimum 'repo' (issues + PRs) - add 'workflow' if needed",
        "Copy the ghp_... token before leaving the page (shown once)",
    ]
    fields = [
        {
            "key": "access_token",
            "label": "Personal Access Token",
            "placeholder": "ghp_...",
            "password": True,
        },
    ]
    config_class = GitHubConfig
    config_fields = [
        {
            "key": "watch_tag",
            "label": "Watch tag",
            "type": "text",
            "placeholder": "@craftbot",
            "help": "Trigger keyword in PR/issue comments. Leave empty to react to all events.",
        },
        {
            "key": "watch_repos",
            "label": "Watched repos",
            "type": "list",
            "placeholder": "owner/repo",
            "help": "Comma-separated. Leave empty to watch every repo the token has access to.",
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: /github login <personal_access_token>\n"
                "Generate one at: https://github.com/settings/tokens"
            )
        token = args[0].strip()

        result = http_request(
            "GET",
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            expected=(200,),
        )
        if "error" in result:
            return False, f"GitHub auth failed: {result['error']}"
        data = result["result"]

        save_credential(
            self.spec.cred_file,
            GitHubCredential(
                access_token=token,
                username=data.get("login", ""),
            ),
        )
        return (
            True,
            f"GitHub connected as @{data.get('login')} ({data.get('name', '')})",
        )

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No GitHub credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed GitHub credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "GitHub: Not connected"
        cred = load_credential(self.spec.cred_file, GitHubCredential)
        if not cred:
            return True, "GitHub: Not connected"
        username = cred.username or "unknown"
        cfg = load_config(_github_config_file(), GitHubConfig) or GitHubConfig()
        tag_info = f" [tag: {cfg.watch_tag}]" if cfg.watch_tag else ""
        repos_info = (
            f" [repos: {', '.join(cfg.watch_repos)}]" if cfg.watch_repos else ""
        )
        return True, f"GitHub: Connected\n  - @{username}{tag_info}{repos_info}"


# -----------------------------------------------------------------
# Client - runtime: REST API + notification polling
# -----------------------------------------------------------------


@register_client
class GitHubClient(BasePlatformClient):
    spec = GITHUB
    PLATFORM_ID = GITHUB.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[GitHubCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._last_modified: Optional[str] = None
        self._seen_ids: set = set()
        self._catchup_done: bool = False

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> GitHubCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, GitHubCredential)
        if self._cred is None:
            raise RuntimeError("No GitHub credentials. Use /github login first.")
        return self._cred

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        return {
            "Authorization": f"Bearer {cred.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        try:
            repo_part, number = recipient.rsplit("#", 1)
            return await self.create_comment(repo_part.strip(), int(number), text)
        except (ValueError, IndexError):
            return {
                "error": f"Invalid recipient format. Use 'owner/repo#number', got: {recipient}"
            }

    # ----- Watch tag / repos (read from github_config.json) -----

    def _config_file(self) -> str:
        # Convention: <cred-stem>_config.json (matches service._config_filename)
        stem = self.spec.cred_file
        return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"

    def _config(self) -> GitHubConfig:
        """Load the runtime config fresh each time. Cheap (small JSON read)
        and avoids stale-cache bugs when the user updates from the UI."""
        return load_config(self._config_file(), GitHubConfig) or GitHubConfig()

    def get_watch_tag(self) -> str:
        return self._config().watch_tag

    def set_watch_tag(self, tag: str) -> None:
        cfg = self._config()
        cfg.watch_tag = tag.strip()
        save_config(self._config_file(), cfg)
        logger.info(f"[GITHUB] Watch tag set to: {cfg.watch_tag or '(disabled)'}")

    def get_watch_repos(self) -> List[str]:
        return list(self._config().watch_repos)

    def set_watch_repos(self, repos: List[str]) -> None:
        cfg = self._config()
        cfg.watch_repos = [r.strip() for r in repos if r.strip()]
        save_config(self._config_file(), cfg)
        logger.info(f"[GITHUB] Watch repos set to: {cfg.watch_repos or '(all)'}")

    # ----- Listening -----

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return

        self._message_callback = callback
        self._load()

        me = await self.get_authenticated_user()
        if "error" in me:
            raise RuntimeError(f"Invalid GitHub token: {me.get('error')}")

        username = me.get("result", {}).get("login", "unknown")
        logger.info(f"[GITHUB] Authenticated as: {username}")

        cred = self._load()
        if cred.username != username:
            cred.username = username
            save_credential(self.spec.cred_file, cred)
            self._cred = cred

        self._last_modified = datetime.now(timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        self._catchup_done = True
        self._listening = True
        self._poll_task = asyncio.create_task(self._poll_loop())

        cfg = self._config()
        tag_info = cfg.watch_tag or "(disabled - all events)"
        repos_info = ", ".join(cfg.watch_repos) if cfg.watch_repos else "(all repos)"
        logger.info(f"[GITHUB] Poller started - tag: {tag_info} | repos: {repos_info}")

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
        logger.info("[GITHUB] Poller stopped")

    async def _poll_loop(self) -> None:
        while self._listening:
            try:
                await self._check_notifications()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[GITHUB] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(POLL_INTERVAL)

    def _check_notifications_sync(self) -> Optional[Dict[str, Any]]:
        """Sync notification poll - returns ``{notifications, last_modified}`` or
        ``None`` if 304/401/other status. Wrapped in ``asyncio.to_thread`` from
        ``_check_notifications`` to avoid anyio's task-tracking issues on
        Python 3.14 conda-forge.
        """
        headers = self._headers()
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified
        try:
            resp = httpx.get(
                f"{GITHUB_API}/notifications",
                headers=headers,
                params={"all": "false", "participating": "true"},
                timeout=30.0,
            )
        except Exception as e:
            logger.warning(f"[GITHUB] Notifications request failed: {e}")
            return None
        if resp.status_code == 304:
            return None
        if resp.status_code == 401:
            logger.warning("[GITHUB] Authentication expired (401)")
            return None
        if resp.status_code != 200:
            logger.warning(f"[GITHUB] Notifications API error: {resp.status_code}")
            return None
        return {
            "notifications": resp.json(),
            "last_modified": resp.headers.get("Last-Modified"),
        }

    async def _check_notifications(self) -> None:
        cfg = self._config()
        result = await asyncio.to_thread(self._check_notifications_sync)
        if result is None:
            return

        if result["last_modified"]:
            self._last_modified = result["last_modified"]

        for notif in result["notifications"]:
            notif_id = notif.get("id", "")
            if notif_id in self._seen_ids:
                continue
            self._seen_ids.add(notif_id)

            repo_full = notif.get("repository", {}).get("full_name", "")
            if cfg.watch_repos and repo_full not in cfg.watch_repos:
                continue

            await self._dispatch_notification(notif)

        if len(self._seen_ids) > 500:
            self._seen_ids = set(list(self._seen_ids)[-200:])

    def _fetch_comment_sync(self, url: str) -> tuple[str, str]:
        """Sync per-comment fetch - returns ``(body, author)`` or ``("", "")``."""
        try:
            cr = httpx.get(url, headers=self._headers(), timeout=15.0)
            if cr.status_code != 200:
                return "", ""
            data = cr.json()
            return data.get("body", ""), data.get("user", {}).get("login", "")
        except Exception:
            return "", ""

    async def _dispatch_notification(self, notif: Dict[str, Any]) -> None:
        if not self._message_callback:
            return

        cfg = self._config()
        reason = notif.get("reason", "")
        subject = notif.get("subject", {})
        subject_type = subject.get("type", "")
        subject_title = subject.get("title", "")
        repo = notif.get("repository", {})
        repo_full = repo.get("full_name", "")

        latest_comment_url = subject.get("latest_comment_url", "")
        comment_body = ""
        comment_author = ""
        if latest_comment_url:
            comment_body, comment_author = await asyncio.to_thread(
                self._fetch_comment_sync,
                latest_comment_url,
            )

        watch_tag = cfg.watch_tag
        if watch_tag:
            if not comment_body or watch_tag.lower() not in comment_body.lower():
                return

            tag_lower = watch_tag.lower()
            idx = comment_body.lower().find(tag_lower)
            instruction = (
                comment_body[idx + len(watch_tag) :].strip()
                if idx >= 0
                else comment_body
            )

            text_parts = [
                f"[{repo_full}] {subject_type}: {subject_title}",
                f"Comment by @{comment_author}: {instruction}",
            ]

            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=comment_author,
                    sender_name=comment_author,
                    text="\n".join(text_parts),
                    channel_id=repo_full,
                    channel_name=repo_full,
                    message_id=notif.get("id", ""),
                    timestamp=datetime.now(timezone.utc),
                    raw={
                        "notification": notif,
                        "trigger": "comment_tag",
                        "tag": watch_tag,
                        "instruction": instruction,
                        "comment_body": comment_body,
                        "comment_author": comment_author,
                    },
                )
            )
            logger.info(
                f"[GITHUB] Tag '{watch_tag}' matched in {repo_full} by @{comment_author}"
            )
            return

        text_parts = [
            f"[{repo_full}] {subject_type}: {subject_title}",
            f"Reason: {reason}",
        ]
        if comment_body:
            text_parts.append(f"Comment by @{comment_author}: {comment_body[:300]}")

        await self._message_callback(
            PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=comment_author or "",
                sender_name=comment_author or reason,
                text="\n".join(text_parts),
                channel_id=repo_full,
                channel_name=repo_full,
                message_id=notif.get("id", ""),
                timestamp=datetime.now(timezone.utc),
                raw=notif,
            )
        )

    # ----- REST API methods -----

    async def get_authenticated_user(self) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/user",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "login": d.get("login"),
                "name": d.get("name"),
                "id": d.get("id"),
            },
        )

    async def list_repos(self, per_page: int = 30, sort: str = "updated") -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/user/repos",
            headers=self._headers(),
            params={"per_page": per_page, "sort": sort},
            expected=(200,),
            transform=lambda d: {
                "repos": [
                    {
                        "full_name": r.get("full_name"),
                        "name": r.get("name"),
                        "private": r.get("private"),
                        "description": r.get("description", ""),
                    }
                    for r in d
                ]
            },
        )

    async def get_repo(self, owner_repo: str, include_metadata: bool = True) -> Result:
        transform = None
        if not include_metadata:
            transform = lambda d: {  # noqa: E731
                "name": d.get("name"),
                "full_name": d.get("full_name"),
                "description": d.get("description"),
                "private": d.get("private"),
                "fork": d.get("fork"),
                "default_branch": d.get("default_branch"),
                "language": d.get("language"),
                "stargazers_count": d.get("stargazers_count"),
                "forks_count": d.get("forks_count"),
                "open_issues_count": d.get("open_issues_count"),
                "topics": d.get("topics", []),
                "archived": d.get("archived"),
                "pushed_at": d.get("pushed_at"),
                "html_url": d.get("html_url"),
                "owner": (d.get("owner") or {}).get("login"),
            }
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}",
            headers=self._headers(),
            expected=(200,),
            transform=transform,
        )

    async def list_issues(
        self, owner_repo: str, state: str = "open", per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/issues",
            headers=self._headers(),
            params={"state": state, "per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "issues": [
                    {
                        "number": i.get("number"),
                        "title": i.get("title"),
                        "state": i.get("state"),
                        "user": i.get("user", {}).get("login", ""),
                        "labels": [label.get("name") for label in i.get("labels", [])],
                        "assignees": [a.get("login") for a in i.get("assignees", [])],
                        "created_at": i.get("created_at"),
                        "updated_at": i.get("updated_at"),
                        "is_pr": "pull_request" in i,
                    }
                    for i in d
                ]
            },
        )

    async def get_issue(
        self, owner_repo: str, number: int, include_metadata: bool = True
    ) -> Result:
        transform = None
        if not include_metadata:
            transform = lambda d: {  # noqa: E731
                "number": d.get("number"),
                "title": d.get("title"),
                "state": d.get("state"),
                "body": d.get("body"),
                "user": (d.get("user") or {}).get("login"),
                "labels": [label.get("name") for label in d.get("labels", [])],
                "assignees": [a.get("login") for a in d.get("assignees", [])],
                "milestone": (d.get("milestone") or {}).get("title"),
                "comments": d.get("comments"),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
                "closed_at": d.get("closed_at"),
                "html_url": d.get("html_url"),
                "is_pr": "pull_request" in d,
            }
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}",
            headers=self._headers(),
            expected=(200,),
            transform=transform,
        )

    async def create_issue(
        self,
        owner_repo: str,
        title: str,
        body: str = "",
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/issues",
            headers=self._headers(),
            json=payload,
            transform=lambda d: {
                "number": d.get("number"),
                "html_url": d.get("html_url"),
                "title": d.get("title"),
            },
        )

    async def create_comment(self, owner_repo: str, number: int, body: str) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/comments",
            headers=self._headers(),
            json={"body": body},
            transform=lambda d: {"id": d.get("id"), "html_url": d.get("html_url")},
        )

    async def list_pull_requests(
        self, owner_repo: str, state: str = "open", per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/pulls",
            headers=self._headers(),
            params={"state": state, "per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "pull_requests": [
                    {
                        "number": p.get("number"),
                        "title": p.get("title"),
                        "state": p.get("state"),
                        "user": p.get("user", {}).get("login", ""),
                        "head": p.get("head", {}).get("ref", ""),
                        "base": p.get("base", {}).get("ref", ""),
                        "draft": p.get("draft", False),
                        "created_at": p.get("created_at"),
                    }
                    for p in d
                ]
            },
        )

    async def search_issues(self, query: str, per_page: int = 20) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/search/issues",
            headers=self._headers(),
            params={"q": query, "per_page": per_page},
            timeout=30.0,
            expected=(200,),
            transform=lambda d: {
                "total_count": d.get("total_count", 0),
                "items": [
                    {
                        "number": i.get("number"),
                        "title": i.get("title"),
                        "state": i.get("state"),
                        "repo": i.get("repository_url", "").split("/repos/")[-1]
                        if i.get("repository_url")
                        else "",
                        "user": i.get("user", {}).get("login", ""),
                        "html_url": i.get("html_url"),
                    }
                    for i in d.get("items", [])
                ],
            },
        )

    async def add_labels(
        self, owner_repo: str, number: int, labels: List[str]
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/labels",
            headers=self._headers(),
            json={"labels": labels},
            expected=(200,),
            transform=lambda _d: {"labels_added": labels},
        )

    async def close_issue(self, owner_repo: str, number: int) -> Result:
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}",
            headers=self._headers(),
            json={"state": "closed"},
            expected=(200,),
            transform=lambda _d: {"closed": True, "number": number},
        )

    # ------------------------------------------------------------------
    # Repos (extended)
    # ------------------------------------------------------------------

    async def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
    ) -> Result:
        payload: Dict[str, Any] = {
            "name": name,
            "private": private,
            "auto_init": auto_init,
        }
        if description:
            payload["description"] = description
        return await arequest(
            "POST",
            f"{GITHUB_API}/user/repos",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "full_name": d.get("full_name"),
                "html_url": d.get("html_url"),
                "private": d.get("private"),
            },
        )

    async def update_repo(
        self,
        owner_repo: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        private: Optional[bool] = None,
        default_branch: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if private is not None:
            payload["private"] = private
        if default_branch is not None:
            payload["default_branch"] = default_branch
        if archived is not None:
            payload["archived"] = archived
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "full_name": d.get("full_name"),
                "html_url": d.get("html_url"),
            },
        )

    async def delete_repo(self, owner_repo: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "repo": owner_repo},
        )

    async def fork_repo(
        self,
        owner_repo: str,
        organization: Optional[str] = None,
        name: Optional[str] = None,
        default_branch_only: bool = False,
    ) -> Result:
        payload: Dict[str, Any] = {"default_branch_only": default_branch_only}
        if organization:
            payload["organization"] = organization
        if name:
            payload["name"] = name
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/forks",
            headers=self._headers(),
            json=payload,
            expected=(202,),
            transform=lambda d: {
                "full_name": d.get("full_name"),
                "html_url": d.get("html_url"),
                "default_branch": d.get("default_branch"),
            },
        )

    async def list_forks(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/forks",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "forks": [
                    {
                        "full_name": f.get("full_name"),
                        "html_url": f.get("html_url"),
                        "owner": f.get("owner", {}).get("login"),
                    }
                    for f in d
                ]
            },
        )

    async def list_collaborators(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/collaborators",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "collaborators": [
                    {"login": u.get("login"), "permissions": u.get("permissions", {})}
                    for u in d
                ]
            },
        )

    async def add_collaborator(
        self, owner_repo: str, username: str, permission: str = "push"
    ) -> Result:
        return await arequest(
            "PUT",
            f"{GITHUB_API}/repos/{owner_repo}/collaborators/{username}",
            headers=self._headers(),
            json={"permission": permission},
            expected=(201, 204),
            transform=lambda d: {
                "added": True,
                "username": username,
                "invitation_id": (d or {}).get("id"),
            },
        )

    async def remove_collaborator(self, owner_repo: str, username: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/collaborators/{username}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"removed": True, "username": username},
        )

    async def get_readme(self, owner_repo: str, ref: Optional[str] = None) -> Result:
        params = {"ref": ref} if ref else None
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/readme",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "name": d.get("name"),
                "path": d.get("path"),
                "download_url": d.get("download_url"),
                "content_b64": d.get("content"),
                "encoding": d.get("encoding"),
            },
        )

    async def list_topics(self, owner_repo: str) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/topics",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {"topics": d.get("names", [])},
        )

    async def set_topics(self, owner_repo: str, names: List[str]) -> Result:
        return await arequest(
            "PUT",
            f"{GITHUB_API}/repos/{owner_repo}/topics",
            headers=self._headers(),
            json={"names": names},
            expected=(200,),
            transform=lambda d: {"topics": d.get("names", [])},
        )

    # ------------------------------------------------------------------
    # Contents (files)
    # ------------------------------------------------------------------

    async def get_file(
        self, owner_repo: str, path: str, ref: Optional[str] = None
    ) -> Result:
        params = {"ref": ref} if ref else None
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/contents/{path}",
            headers=self._headers(),
            params=params,
            expected=(200,),
        )

    async def create_or_update_file(
        self,
        owner_repo: str,
        path: str,
        message: str,
        content_b64: str,
        sha: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"message": message, "content": content_b64}
        if sha:
            payload["sha"] = sha
        if branch:
            payload["branch"] = branch
        return await arequest(
            "PUT",
            f"{GITHUB_API}/repos/{owner_repo}/contents/{path}",
            headers=self._headers(),
            json=payload,
            expected=(200, 201),
            transform=lambda d: {
                "path": d.get("content", {}).get("path"),
                "content_sha": d.get("content", {}).get("sha"),
                "content_html_url": d.get("content", {}).get("html_url"),
                "commit_sha": d.get("commit", {}).get("sha"),
                "commit_html_url": d.get("commit", {}).get("html_url"),
            },
        )

    async def delete_file(
        self,
        owner_repo: str,
        path: str,
        message: str,
        sha: str,
        branch: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"message": message, "sha": sha}
        if branch:
            payload["branch"] = branch
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/contents/{path}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "commit_sha": d.get("commit", {}).get("sha"),
                "deleted": True,
            },
        )

    # ------------------------------------------------------------------
    # Branches / refs
    # ------------------------------------------------------------------

    async def list_branches(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/branches",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "branches": [
                    {
                        "name": b.get("name"),
                        "sha": b.get("commit", {}).get("sha"),
                        "protected": b.get("protected"),
                    }
                    for b in d
                ]
            },
        )

    async def get_branch(self, owner_repo: str, branch: str) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/branches/{branch}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "name": d.get("name"),
                "sha": d.get("commit", {}).get("sha"),
                "protected": d.get("protected"),
            },
        )

    async def create_branch(
        self, owner_repo: str, branch: str, from_sha: str
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/git/refs",
            headers=self._headers(),
            json={"ref": f"refs/heads/{branch}", "sha": from_sha},
            expected=(201,),
            transform=lambda d: {
                "ref": d.get("ref"),
                "sha": d.get("object", {}).get("sha"),
            },
        )

    async def delete_branch(self, owner_repo: str, branch: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/git/refs/heads/{branch}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "branch": branch},
        )

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------

    async def list_commits(
        self,
        owner_repo: str,
        sha: Optional[str] = None,
        path: Optional[str] = None,
        author: Optional[str] = None,
        per_page: int = 30,
    ) -> Result:
        params: Dict[str, Any] = {"per_page": per_page}
        if sha:
            params["sha"] = sha
        if path:
            params["path"] = path
        if author:
            params["author"] = author
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/commits",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "commits": [
                    {
                        "sha": c.get("sha"),
                        "message": (c.get("commit", {}).get("message") or "").split(
                            "\n"
                        )[0],
                        "author": c.get("commit", {}).get("author", {}).get("name"),
                        "date": c.get("commit", {}).get("author", {}).get("date"),
                        "html_url": c.get("html_url"),
                    }
                    for c in d
                ]
            },
        )

    async def get_commit(
        self, owner_repo: str, sha: str, include_metadata: bool = True
    ) -> Result:
        transform = None
        if not include_metadata:

            def _person(d: Dict[str, Any], key: str) -> Dict[str, Any]:
                git_person = (d.get("commit") or {}).get(key) or {}
                return {
                    "name": git_person.get("name"),
                    "email": git_person.get("email"),
                    "date": git_person.get("date"),
                    "login": (d.get(key) or {}).get("login"),
                }

            transform = lambda d: {  # noqa: E731
                "sha": d.get("sha"),
                "message": (d.get("commit") or {}).get("message"),
                "author": _person(d, "author"),
                "committer": _person(d, "committer"),
                "stats": d.get("stats"),
                "parents": [p.get("sha") for p in d.get("parents", [])],
                "files": [
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                        "patch": f.get("patch"),
                    }
                    for f in d.get("files", [])
                ],
                "html_url": d.get("html_url"),
            }
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/commits/{sha}",
            headers=self._headers(),
            expected=(200,),
            transform=transform,
        )

    async def compare_commits(self, owner_repo: str, base: str, head: str) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/compare/{base}...{head}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "status": d.get("status"),
                "ahead_by": d.get("ahead_by"),
                "behind_by": d.get("behind_by"),
                "total_commits": d.get("total_commits"),
                "files": [
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                    }
                    for f in d.get("files", [])
                ],
            },
        )

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    async def get_pull_request(
        self, owner_repo: str, number: int, include_metadata: bool = True
    ) -> Result:
        transform = None
        if not include_metadata:
            transform = lambda d: {  # noqa: E731
                "number": d.get("number"),
                "title": d.get("title"),
                "state": d.get("state"),
                "body": d.get("body"),
                "draft": d.get("draft"),
                "merged": d.get("merged"),
                "mergeable": d.get("mergeable"),
                "merged_by": (d.get("merged_by") or {}).get("login"),
                "user": (d.get("user") or {}).get("login"),
                "labels": [label.get("name") for label in d.get("labels", [])],
                "assignees": [a.get("login") for a in d.get("assignees", [])],
                "requested_reviewers": [
                    u.get("login") for u in d.get("requested_reviewers", [])
                ],
                "milestone": (d.get("milestone") or {}).get("title"),
                "base": {
                    "ref": (d.get("base") or {}).get("ref"),
                    "sha": (d.get("base") or {}).get("sha"),
                },
                "head": {
                    "ref": (d.get("head") or {}).get("ref"),
                    "sha": (d.get("head") or {}).get("sha"),
                    "repo": ((d.get("head") or {}).get("repo") or {}).get("full_name"),
                },
                "commits": d.get("commits"),
                "additions": d.get("additions"),
                "deletions": d.get("deletions"),
                "changed_files": d.get("changed_files"),
                "comments": d.get("comments"),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
                "closed_at": d.get("closed_at"),
                "merged_at": d.get("merged_at"),
                "html_url": d.get("html_url"),
            }
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}",
            headers=self._headers(),
            expected=(200,),
            transform=transform,
        )

    async def create_pull_request(
        self,
        owner_repo: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
        maintainer_can_modify: bool = True,
    ) -> Result:
        payload: Dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
            "maintainer_can_modify": maintainer_can_modify,
        }
        if body:
            payload["body"] = body
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/pulls",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "number": d.get("number"),
                "html_url": d.get("html_url"),
                "title": d.get("title"),
                "state": d.get("state"),
            },
        )

    async def update_pull_request(
        self,
        owner_repo: str,
        number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        base: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if base is not None:
            payload["base"] = base
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "number": d.get("number"),
                "state": d.get("state"),
                "html_url": d.get("html_url"),
            },
        )

    async def merge_pull_request(
        self,
        owner_repo: str,
        number: int,
        commit_title: Optional[str] = None,
        commit_message: Optional[str] = None,
        sha: Optional[str] = None,
        merge_method: str = "merge",
    ) -> Result:
        payload: Dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        if sha:
            payload["sha"] = sha
        return await arequest(
            "PUT",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/merge",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "merged": d.get("merged"),
                "sha": d.get("sha"),
                "message": d.get("message"),
            },
        )

    async def list_pr_files(
        self, owner_repo: str, number: int, per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/files",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "files": [
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                        "patch": (f.get("patch") or "")[:500],
                    }
                    for f in d
                ]
            },
        )

    async def list_pr_commits(
        self, owner_repo: str, number: int, per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/commits",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "commits": [
                    {
                        "sha": c.get("sha"),
                        "message": (c.get("commit", {}).get("message") or "").split(
                            "\n"
                        )[0],
                        "author": c.get("commit", {}).get("author", {}).get("name"),
                    }
                    for c in d
                ]
            },
        )

    async def request_pr_reviewers(
        self,
        owner_repo: str,
        number: int,
        reviewers: Optional[List[str]] = None,
        team_reviewers: Optional[List[str]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if reviewers:
            payload["reviewers"] = reviewers
        if team_reviewers:
            payload["team_reviewers"] = team_reviewers
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/requested_reviewers",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "requested": True,
                "reviewers": [u.get("login") for u in d.get("requested_reviewers", [])],
            },
        )

    async def remove_pr_reviewers(
        self,
        owner_repo: str,
        number: int,
        reviewers: Optional[List[str]] = None,
        team_reviewers: Optional[List[str]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if reviewers:
            payload["reviewers"] = reviewers
        if team_reviewers:
            payload["team_reviewers"] = team_reviewers
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/requested_reviewers",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda _d: {
                "removed": True,
                "reviewers": reviewers or [],
                "team_reviewers": team_reviewers or [],
            },
        )

    async def create_pr_review(
        self,
        owner_repo: str,
        number: int,
        body: str = "",
        event: Optional[str] = None,
        comments: Optional[List[Dict[str, Any]]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if body:
            payload["body"] = body
        if event:
            payload["event"] = event
        if comments:
            payload["comments"] = comments
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/reviews",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "state": d.get("state"),
                "html_url": d.get("html_url"),
            },
        )

    async def list_pr_reviews(
        self, owner_repo: str, number: int, per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/reviews",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "reviews": [
                    {
                        "id": r.get("id"),
                        "user": r.get("user", {}).get("login"),
                        "state": r.get("state"),
                        "body": r.get("body"),
                        "submitted_at": r.get("submitted_at"),
                    }
                    for r in d
                ]
            },
        )

    async def submit_pr_review(
        self, owner_repo: str, number: int, review_id: int, event: str, body: str = ""
    ) -> Result:
        payload: Dict[str, Any] = {"event": event}
        if body:
            payload["body"] = body
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/reviews/{review_id}/events",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "state": d.get("state")},
        )

    async def list_pr_review_comments(
        self, owner_repo: str, number: int, per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/comments",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "comments": [
                    {
                        "id": c.get("id"),
                        "user": c.get("user", {}).get("login"),
                        "body": c.get("body"),
                        "path": c.get("path"),
                        "line": c.get("line"),
                    }
                    for c in d
                ]
            },
        )

    async def create_pr_review_comment(
        self,
        owner_repo: str,
        number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/{number}/comments",
            headers=self._headers(),
            json={
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": side,
            },
            expected=(201,),
            transform=lambda d: {"id": d.get("id"), "html_url": d.get("html_url")},
        )

    # ------------------------------------------------------------------
    # Issues (gaps)
    # ------------------------------------------------------------------

    async def update_issue(
        self,
        owner_repo: str,
        number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        milestone: Optional[int] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels
        if assignees is not None:
            payload["assignees"] = assignees
        if milestone is not None:
            payload["milestone"] = milestone
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "number": d.get("number"),
                "state": d.get("state"),
                "html_url": d.get("html_url"),
            },
        )

    async def lock_issue(
        self, owner_repo: str, number: int, lock_reason: Optional[str] = None
    ) -> Result:
        payload: Dict[str, Any] = {}
        if lock_reason:
            payload["lock_reason"] = lock_reason
        return await arequest(
            "PUT",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/lock",
            headers=self._headers(),
            json=payload,
            expected=(204,),
            transform=lambda _d: {"locked": True, "number": number},
        )

    async def unlock_issue(self, owner_repo: str, number: int) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/lock",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"unlocked": True, "number": number},
        )

    async def list_issue_comments(
        self, owner_repo: str, number: int, per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/comments",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "comments": [
                    {
                        "id": c.get("id"),
                        "user": c.get("user", {}).get("login"),
                        "body": c.get("body"),
                        "created_at": c.get("created_at"),
                    }
                    for c in d
                ]
            },
        )

    async def update_issue_comment(
        self, owner_repo: str, comment_id: int, body: str
    ) -> Result:
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/issues/comments/{comment_id}",
            headers=self._headers(),
            json={"body": body},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "html_url": d.get("html_url")},
        )

    async def delete_issue_comment(self, owner_repo: str, comment_id: int) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/issues/comments/{comment_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "comment_id": comment_id},
        )

    async def list_issue_events(
        self, owner_repo: str, number: int, per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/events",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "events": [
                    {
                        "id": e.get("id"),
                        "actor": e.get("actor", {}).get("login"),
                        "event": e.get("event"),
                        "created_at": e.get("created_at"),
                    }
                    for e in d
                ]
            },
        )

    async def remove_issue_label(
        self, owner_repo: str, number: int, name: str
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/labels/{name}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {"labels": [label.get("name") for label in d]},
        )

    async def set_issue_labels(
        self, owner_repo: str, number: int, labels: List[str]
    ) -> Result:
        return await arequest(
            "PUT",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/labels",
            headers=self._headers(),
            json={"labels": labels},
            expected=(200,),
            transform=lambda d: {"labels": [label.get("name") for label in d]},
        )

    async def add_assignees(
        self, owner_repo: str, number: int, assignees: List[str]
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/assignees",
            headers=self._headers(),
            json={"assignees": assignees},
            expected=(201,),
            transform=lambda d: {
                "number": d.get("number"),
                "assignees": [a.get("login") for a in d.get("assignees", [])],
            },
        )

    async def remove_assignees(
        self, owner_repo: str, number: int, assignees: List[str]
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/assignees",
            headers=self._headers(),
            json={"assignees": assignees},
            expected=(200,),
            transform=lambda d: {
                "number": d.get("number"),
                "assignees": [a.get("login") for a in d.get("assignees", [])],
            },
        )

    # ------------------------------------------------------------------
    # Labels (repo)
    # ------------------------------------------------------------------

    async def list_repo_labels(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/labels",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "labels": [
                    {
                        "name": label.get("name"),
                        "color": label.get("color"),
                        "description": label.get("description"),
                    }
                    for label in d
                ]
            },
        )

    async def create_label(
        self, owner_repo: str, name: str, color: str = "ededed", description: str = ""
    ) -> Result:
        payload: Dict[str, Any] = {"name": name, "color": color}
        if description:
            payload["description"] = description
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/labels",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "name": d.get("name"),
                "color": d.get("color"),
                "url": d.get("url"),
            },
        )

    async def update_label(
        self,
        owner_repo: str,
        name: str,
        new_name: Optional[str] = None,
        color: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if new_name is not None:
            payload["new_name"] = new_name
        if color is not None:
            payload["color"] = color
        if description is not None:
            payload["description"] = description
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/labels/{name}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "name": d.get("name"),
                "color": d.get("color"),
                "description": d.get("description"),
            },
        )

    async def delete_label(self, owner_repo: str, name: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/labels/{name}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "name": name},
        )

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------

    async def list_milestones(
        self, owner_repo: str, state: str = "open", per_page: int = 30
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/milestones",
            headers=self._headers(),
            params={"state": state, "per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "milestones": [
                    {
                        "number": m.get("number"),
                        "title": m.get("title"),
                        "state": m.get("state"),
                        "due_on": m.get("due_on"),
                        "open_issues": m.get("open_issues"),
                        "closed_issues": m.get("closed_issues"),
                    }
                    for m in d
                ]
            },
        )

    async def create_milestone(
        self,
        owner_repo: str,
        title: str,
        state: str = "open",
        description: str = "",
        due_on: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"title": title, "state": state}
        if description:
            payload["description"] = description
        if due_on:
            payload["due_on"] = due_on
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/milestones",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "number": d.get("number"),
                "title": d.get("title"),
                "html_url": d.get("html_url"),
            },
        )

    async def update_milestone(
        self,
        owner_repo: str,
        number: int,
        title: Optional[str] = None,
        state: Optional[str] = None,
        description: Optional[str] = None,
        due_on: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if state is not None:
            payload["state"] = state
        if description is not None:
            payload["description"] = description
        if due_on is not None:
            payload["due_on"] = due_on
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/milestones/{number}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "number": d.get("number"),
                "title": d.get("title"),
                "state": d.get("state"),
            },
        )

    async def delete_milestone(self, owner_repo: str, number: int) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/milestones/{number}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "number": number},
        )

    # ------------------------------------------------------------------
    # Releases & tags
    # ------------------------------------------------------------------

    async def list_releases(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/releases",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "releases": [
                    {
                        "id": r.get("id"),
                        "tag_name": r.get("tag_name"),
                        "name": r.get("name"),
                        "draft": r.get("draft"),
                        "prerelease": r.get("prerelease"),
                        "published_at": r.get("published_at"),
                        "html_url": r.get("html_url"),
                    }
                    for r in d
                ]
            },
        )

    async def get_release(
        self,
        owner_repo: str,
        release_id: Optional[int] = None,
        tag: Optional[str] = None,
        latest: bool = False,
        include_metadata: bool = True,
    ) -> Result:
        if latest:
            url = f"{GITHUB_API}/repos/{owner_repo}/releases/latest"
        elif tag:
            url = f"{GITHUB_API}/repos/{owner_repo}/releases/tags/{tag}"
        elif release_id is not None:
            url = f"{GITHUB_API}/repos/{owner_repo}/releases/{release_id}"
        else:
            return {"error": "Must provide release_id, tag, or latest=True"}
        transform = None
        if not include_metadata:
            transform = lambda d: {  # noqa: E731
                "id": d.get("id"),
                "tag_name": d.get("tag_name"),
                "name": d.get("name"),
                "body": d.get("body"),
                "draft": d.get("draft"),
                "prerelease": d.get("prerelease"),
                "created_at": d.get("created_at"),
                "published_at": d.get("published_at"),
                "html_url": d.get("html_url"),
                "author": (d.get("author") or {}).get("login"),
                "assets": [
                    {
                        "name": a.get("name"),
                        "size": a.get("size"),
                        "download_count": a.get("download_count"),
                        "browser_download_url": a.get("browser_download_url"),
                    }
                    for a in d.get("assets", [])
                ],
            }
        return await arequest(
            "GET", url, headers=self._headers(), expected=(200,), transform=transform
        )

    async def create_release(
        self,
        owner_repo: str,
        tag_name: str,
        name: Optional[str] = None,
        body: str = "",
        draft: bool = False,
        prerelease: bool = False,
        target_commitish: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {
            "tag_name": tag_name,
            "draft": draft,
            "prerelease": prerelease,
        }
        if name:
            payload["name"] = name
        if body:
            payload["body"] = body
        if target_commitish:
            payload["target_commitish"] = target_commitish
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/releases",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "id": d.get("id"),
                "tag_name": d.get("tag_name"),
                "html_url": d.get("html_url"),
            },
        )

    async def update_release(
        self,
        owner_repo: str,
        release_id: int,
        tag_name: Optional[str] = None,
        name: Optional[str] = None,
        body: Optional[str] = None,
        draft: Optional[bool] = None,
        prerelease: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if tag_name is not None:
            payload["tag_name"] = tag_name
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["body"] = body
        if draft is not None:
            payload["draft"] = draft
        if prerelease is not None:
            payload["prerelease"] = prerelease
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/repos/{owner_repo}/releases/{release_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "tag_name": d.get("tag_name"),
                "html_url": d.get("html_url"),
            },
        )

    async def delete_release(self, owner_repo: str, release_id: int) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/releases/{release_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "release_id": release_id},
        )

    async def list_tags(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/tags",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "tags": [
                    {"name": t.get("name"), "sha": t.get("commit", {}).get("sha")}
                    for t in d
                ]
            },
        )

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    async def add_issue_reaction(
        self, owner_repo: str, number: int, content: str
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/reactions",
            headers=self._headers(),
            json={"content": content},
            expected=(200, 201),
            transform=lambda d: {"id": d.get("id"), "content": d.get("content")},
        )

    async def add_issue_comment_reaction(
        self, owner_repo: str, comment_id: int, content: str
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/issues/comments/{comment_id}/reactions",
            headers=self._headers(),
            json={"content": content},
            expected=(200, 201),
            transform=lambda d: {"id": d.get("id"), "content": d.get("content")},
        )

    async def add_pr_review_comment_reaction(
        self, owner_repo: str, comment_id: int, content: str
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/comments/{comment_id}/reactions",
            headers=self._headers(),
            json={"content": content},
            expected=(200, 201),
            transform=lambda d: {"id": d.get("id"), "content": d.get("content")},
        )

    async def delete_issue_reaction(
        self, owner_repo: str, number: int, reaction_id: int
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/issues/{number}/reactions/{reaction_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "reaction_id": reaction_id},
        )

    async def delete_issue_comment_reaction(
        self, owner_repo: str, comment_id: int, reaction_id: int
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/issues/comments/{comment_id}/reactions/{reaction_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "reaction_id": reaction_id},
        )

    async def delete_pr_review_comment_reaction(
        self, owner_repo: str, comment_id: int, reaction_id: int
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/repos/{owner_repo}/pulls/comments/{comment_id}/reactions/{reaction_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "reaction_id": reaction_id},
        )

    # ------------------------------------------------------------------
    # Search (extended)
    # ------------------------------------------------------------------

    async def search_repos(self, query: str, per_page: int = 20) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/search/repositories",
            headers=self._headers(),
            params={"q": query, "per_page": per_page},
            timeout=30.0,
            expected=(200,),
            transform=lambda d: {
                "total_count": d.get("total_count", 0),
                "items": [
                    {
                        "full_name": r.get("full_name"),
                        "html_url": r.get("html_url"),
                        "description": r.get("description"),
                        "stars": r.get("stargazers_count"),
                        "language": r.get("language"),
                    }
                    for r in d.get("items", [])
                ],
            },
        )

    async def search_code(self, query: str, per_page: int = 20) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/search/code",
            headers=self._headers(),
            params={"q": query, "per_page": per_page},
            timeout=30.0,
            expected=(200,),
            transform=lambda d: {
                "total_count": d.get("total_count", 0),
                "items": [
                    {
                        "name": i.get("name"),
                        "path": i.get("path"),
                        "repo": i.get("repository", {}).get("full_name"),
                        "html_url": i.get("html_url"),
                    }
                    for i in d.get("items", [])
                ],
            },
        )

    async def search_users(self, query: str, per_page: int = 20) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/search/users",
            headers=self._headers(),
            params={"q": query, "per_page": per_page},
            timeout=30.0,
            expected=(200,),
            transform=lambda d: {
                "total_count": d.get("total_count", 0),
                "items": [
                    {
                        "login": u.get("login"),
                        "html_url": u.get("html_url"),
                        "type": u.get("type"),
                    }
                    for u in d.get("items", [])
                ],
            },
        )

    async def search_commits(self, query: str, per_page: int = 20) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/search/commits",
            headers=self._headers(),
            params={"q": query, "per_page": per_page},
            timeout=30.0,
            expected=(200,),
            transform=lambda d: {
                "total_count": d.get("total_count", 0),
                "items": [
                    {
                        "sha": c.get("sha"),
                        "message": (c.get("commit", {}).get("message") or "").split(
                            "\n"
                        )[0],
                        "repo": c.get("repository", {}).get("full_name"),
                        "html_url": c.get("html_url"),
                    }
                    for c in d.get("items", [])
                ],
            },
        )

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def get_user(self, username: str) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/users/{username}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "login": d.get("login"),
                "name": d.get("name"),
                "bio": d.get("bio"),
                "public_repos": d.get("public_repos"),
                "followers": d.get("followers"),
                "following": d.get("following"),
                "html_url": d.get("html_url"),
            },
        )

    async def list_user_repos(
        self, username: str, per_page: int = 30, sort: str = "updated"
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/users/{username}/repos",
            headers=self._headers(),
            params={"per_page": per_page, "sort": sort},
            expected=(200,),
            transform=lambda d: {
                "repos": [
                    {
                        "full_name": r.get("full_name"),
                        "html_url": r.get("html_url"),
                        "description": r.get("description"),
                        "stars": r.get("stargazers_count"),
                        "language": r.get("language"),
                    }
                    for r in d
                ]
            },
        )

    async def follow_user(self, username: str) -> Result:
        return await arequest(
            "PUT",
            f"{GITHUB_API}/user/following/{username}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"followed": True, "username": username},
        )

    async def unfollow_user(self, username: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/user/following/{username}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"unfollowed": True, "username": username},
        )

    async def list_followers(self, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/user/followers",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {"followers": [u.get("login") for u in d]},
        )

    async def list_following(self, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/user/following",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {"following": [u.get("login") for u in d]},
        )

    # ------------------------------------------------------------------
    # Stars
    # ------------------------------------------------------------------

    async def star_repo(self, owner_repo: str) -> Result:
        return await arequest(
            "PUT",
            f"{GITHUB_API}/user/starred/{owner_repo}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"starred": True, "repo": owner_repo},
        )

    async def unstar_repo(self, owner_repo: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/user/starred/{owner_repo}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"unstarred": True, "repo": owner_repo},
        )

    async def list_starred(self, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/user/starred",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "starred": [
                    {"full_name": r.get("full_name"), "html_url": r.get("html_url")}
                    for r in d
                ]
            },
        )

    async def list_stargazers(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/stargazers",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {"stargazers": [u.get("login") for u in d]},
        )

    # ------------------------------------------------------------------
    # Gists
    # ------------------------------------------------------------------

    async def list_gists(self, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/gists",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "gists": [
                    {
                        "id": g.get("id"),
                        "description": g.get("description"),
                        "public": g.get("public"),
                        "html_url": g.get("html_url"),
                        "files": list(g.get("files", {}).keys()),
                    }
                    for g in d
                ]
            },
        )

    async def get_gist(self, gist_id: str, include_metadata: bool = True) -> Result:
        transform = None
        if not include_metadata:
            transform = lambda d: {  # noqa: E731
                "id": d.get("id"),
                "description": d.get("description"),
                "public": d.get("public"),
                "html_url": d.get("html_url"),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
                "owner": (d.get("owner") or {}).get("login"),
                "files": {
                    name: {
                        "filename": f.get("filename"),
                        "language": f.get("language"),
                        "size": f.get("size"),
                        "truncated": f.get("truncated"),
                        "content": f.get("content"),
                    }
                    for name, f in (d.get("files") or {}).items()
                },
            }
        return await arequest(
            "GET",
            f"{GITHUB_API}/gists/{gist_id}",
            headers=self._headers(),
            expected=(200,),
            transform=transform,
        )

    async def create_gist(
        self,
        files: Dict[str, Dict[str, str]],
        description: str = "",
        public: bool = True,
    ) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/gists",
            headers=self._headers(),
            json={"description": description, "public": public, "files": files},
            expected=(201,),
            transform=lambda d: {"id": d.get("id"), "html_url": d.get("html_url")},
        )

    async def update_gist(
        self,
        gist_id: str,
        description: Optional[str] = None,
        files: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if description is not None:
            payload["description"] = description
        if files is not None:
            payload["files"] = files
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/gists/{gist_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "html_url": d.get("html_url")},
        )

    async def delete_gist(self, gist_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{GITHUB_API}/gists/{gist_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "gist_id": gist_id},
        )

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    async def list_notifications(
        self,
        include_read: bool = False,
        participating: bool = False,
        per_page: int = 30,
    ) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/notifications",
            headers=self._headers(),
            params={
                "all": str(include_read).lower(),
                "participating": str(participating).lower(),
                "per_page": per_page,
            },
            expected=(200,),
            transform=lambda d: {
                "notifications": [
                    {
                        "id": n.get("id"),
                        "reason": n.get("reason"),
                        "unread": n.get("unread"),
                        "repo": n.get("repository", {}).get("full_name"),
                        "subject": n.get("subject", {}).get("title"),
                        "type": n.get("subject", {}).get("type"),
                    }
                    for n in d
                ]
            },
        )

    async def mark_all_notifications_read(
        self, last_read_at: Optional[str] = None
    ) -> Result:
        payload: Dict[str, Any] = {}
        if last_read_at:
            payload["last_read_at"] = last_read_at
        return await arequest(
            "PUT",
            f"{GITHUB_API}/notifications",
            headers=self._headers(),
            json=payload,
            expected=(202, 205),
            transform=lambda _d: {"marked_read": True},
        )

    async def mark_notification_read(self, thread_id: str) -> Result:
        return await arequest(
            "PATCH",
            f"{GITHUB_API}/notifications/threads/{thread_id}",
            headers=self._headers(),
            expected=(205,),
            transform=lambda _d: {"marked_read": True, "thread_id": thread_id},
        )

    # ------------------------------------------------------------------
    # Workflows / Actions (CI)
    # ------------------------------------------------------------------

    async def list_workflows(self, owner_repo: str, per_page: int = 30) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/actions/workflows",
            headers=self._headers(),
            params={"per_page": per_page},
            expected=(200,),
            transform=lambda d: {
                "workflows": [
                    {
                        "id": w.get("id"),
                        "name": w.get("name"),
                        "path": w.get("path"),
                        "state": w.get("state"),
                    }
                    for w in d.get("workflows", [])
                ]
            },
        )

    async def list_workflow_runs(
        self,
        owner_repo: str,
        workflow_id: Optional[str] = None,
        branch: Optional[str] = None,
        status: Optional[str] = None,
        per_page: int = 30,
    ) -> Result:
        params: Dict[str, Any] = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        if status:
            params["status"] = status
        url = (
            f"{GITHUB_API}/repos/{owner_repo}/actions/workflows/{workflow_id}/runs"
            if workflow_id
            else f"{GITHUB_API}/repos/{owner_repo}/actions/runs"
        )
        return await arequest(
            "GET",
            url,
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "workflow_runs": [
                    {
                        "id": r.get("id"),
                        "name": r.get("name"),
                        "status": r.get("status"),
                        "conclusion": r.get("conclusion"),
                        "branch": r.get("head_branch"),
                        "html_url": r.get("html_url"),
                        "created_at": r.get("created_at"),
                    }
                    for r in d.get("workflow_runs", [])
                ]
            },
        )

    async def get_workflow_run(self, owner_repo: str, run_id: int) -> Result:
        return await arequest(
            "GET",
            f"{GITHUB_API}/repos/{owner_repo}/actions/runs/{run_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("name"),
                "status": d.get("status"),
                "conclusion": d.get("conclusion"),
                "branch": d.get("head_branch"),
                "html_url": d.get("html_url"),
            },
        )

    async def trigger_workflow(
        self,
        owner_repo: str,
        workflow_id: str,
        ref: str,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/actions/workflows/{workflow_id}/dispatches",
            headers=self._headers(),
            json=payload,
            expected=(204,),
            transform=lambda _d: {
                "triggered": True,
                "workflow_id": workflow_id,
                "ref": ref,
            },
        )

    async def cancel_workflow_run(self, owner_repo: str, run_id: int) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/actions/runs/{run_id}/cancel",
            headers=self._headers(),
            expected=(202,),
            transform=lambda _d: {"cancelled": True, "run_id": run_id},
        )

    async def rerun_workflow_run(self, owner_repo: str, run_id: int) -> Result:
        return await arequest(
            "POST",
            f"{GITHUB_API}/repos/{owner_repo}/actions/runs/{run_id}/rerun",
            headers=self._headers(),
            expected=(201,),
            transform=lambda _d: {"rerun": True, "run_id": run_id},
        )

    async def get_workflow_run_logs_url(self, owner_repo: str, run_id: int) -> Result:
        """Return the signed redirect URL to the logs zip. Does NOT download.

        Logs are served via a 302 to a signed S3 URL. Following the redirect
        would stream a potentially large zip into agent memory, so the agent
        gets the URL back and downloads it itself if needed.
        """
        try:
            r = httpx.get(
                f"{GITHUB_API}/repos/{owner_repo}/actions/runs/{run_id}/logs",
                headers=self._headers(),
                follow_redirects=False,
                timeout=15.0,
            )
            if r.status_code == 302:
                return {
                    "ok": True,
                    "result": {"logs_url": r.headers.get("location", "")},
                }
            return {"error": f"API error: {r.status_code}", "details": r.text}
        except Exception as e:
            return {"error": str(e)}
