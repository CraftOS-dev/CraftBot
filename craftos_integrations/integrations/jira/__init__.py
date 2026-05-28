# -*- coding: utf-8 -*-
"""Jira integration - handler + client + credential."""

from __future__ import annotations

import asyncio
import base64
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
from ...helpers import Result, arequest
from ...logger import get_logger

logger = get_logger(__name__)

JIRA_CLOUD_API = "https://api.atlassian.com/ex/jira"
POLL_INTERVAL = 10
RETRY_DELAY = 15


@dataclass
class JiraCredential:
    domain: str = ""
    email: str = ""
    api_token: str = ""
    cloud_id: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_expiry: float = 0.0
    site_url: str = ""


@dataclass
class JiraConfig:
    """Runtime knobs separate from the credential. Persisted as
    ``jira_config.json`` next to ``jira.json``."""

    watch_tag: str = ""
    watch_labels: List[str] = field(default_factory=list)


JIRA = IntegrationSpec(
    name="jira",
    cred_class=JiraCredential,
    cred_file="jira.json",
    platform_id="jira",
)


def _jira_config_file() -> str:
    """``jira.json`` â†’ ``jira_config.json``."""
    stem = JIRA.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(JIRA.name)
class JiraHandler(IntegrationHandler):
    spec = JIRA
    display_name = "Jira"
    description = "Issue tracking and project management"
    auth_type = "token"
    icon = "jira"
    connect_help = [
        "Domain â†’ your Jira URL host (e.g. mycompany.atlassian.net)",
        "Email â†’ the address you log into Jira with",
        "API Token: open id.atlassian.com/manage-profile/security/api-tokens",
        "Click 'Create API token', label it (e.g. 'CraftBot'), copy the value",
    ]
    fields = [
        {
            "key": "domain",
            "label": "Jira Domain",
            "placeholder": "mycompany.atlassian.net",
            "password": False,
        },
        {
            "key": "email",
            "label": "Email",
            "placeholder": "you@example.com",
            "password": False,
        },
        {
            "key": "api_token",
            "label": "API Token",
            "placeholder": "Enter Jira API token",
            "password": True,
        },
    ]
    config_class = JiraConfig
    config_fields = [
        {
            "key": "watch_tag",
            "label": "Watch tag",
            "type": "text",
            "placeholder": "@craftbot",
            "help": "Trigger keyword in issue comments. Leave empty to react to all updates.",
        },
        {
            "key": "watch_labels",
            "label": "Watched labels",
            "type": "list",
            "placeholder": "bug",
            "help": "Comma-separated. Leave empty to watch issues with any label.",
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 3:
            return False, (
                "Usage: /jira login <domain> <email> <api_token>\n"
                "Get an API token from https://id.atlassian.com/manage-profile/security/api-tokens"
            )
        domain, email, api_token = args[0], args[1], args[2]

        clean_domain = domain.strip().rstrip("/")
        if clean_domain.startswith("https://"):
            clean_domain = clean_domain[len("https://") :]
        if clean_domain.startswith("http://"):
            clean_domain = clean_domain[len("http://") :]
        if "." not in clean_domain:
            clean_domain = f"{clean_domain}.atlassian.net"

        email = email.strip()
        api_token = api_token.strip()

        raw_auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        auth_headers = {
            "Authorization": f"Basic {raw_auth}",
            "Accept": "application/json",
        }

        data = None
        last_status = 0
        for api_ver in ("3", "2"):
            url = f"https://{clean_domain}/rest/api/{api_ver}/myself"
            logger.info(f"[Jira] Trying {url} with email={email}")
            try:
                r = httpx.get(
                    url, headers=auth_headers, timeout=15, follow_redirects=True
                )
            except httpx.ConnectError:
                return (
                    False,
                    f"Cannot connect to https://{clean_domain} - check the domain name.",
                )
            except Exception as e:
                return False, f"Jira connection error: {e}"
            if r.status_code == 200:
                data = r.json()
                break
            logger.warning(
                f"[Jira] API v{api_ver} returned HTTP {r.status_code}: {r.text[:300]}"
            )
            last_status = r.status_code

        if data is None:
            hints = [f"Tried: https://{clean_domain}/rest/api/3/myself"]
            if last_status == 401:
                hints.append(
                    "Ensure you are using an API token, not your account password."
                )
                hints.append(
                    "The email must match your Atlassian account email exactly."
                )
                hints.append(
                    "Generate a token at: https://id.atlassian.com/manage-profile/security/api-tokens"
                )
            elif last_status == 403:
                hints.append(
                    "Your account may not have REST API access. Check Jira permissions."
                )
            elif last_status == 404:
                hints.append(
                    f"Domain '{clean_domain}' not reachable or has no REST API."
                )
            hint_str = "\n".join(f"  - {h}" for h in hints)
            return False, f"Jira auth failed (HTTP {last_status}).\n{hint_str}"

        save_credential(
            self.spec.cred_file,
            JiraCredential(
                domain=clean_domain,
                email=email,
                api_token=api_token,
            ),
        )
        display_name = data.get("displayName", email)
        return True, f"Jira connected as {display_name} ({clean_domain})"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Jira credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed Jira credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Jira: Not connected"
        cred = load_credential(self.spec.cred_file, JiraCredential)
        if not cred:
            return True, "Jira: Not connected"
        domain = cred.domain or cred.site_url or "unknown"
        email = cred.email or "OAuth"
        cfg = load_config(_jira_config_file(), JiraConfig) or JiraConfig()
        label_info = (
            f" [watching: {', '.join(cfg.watch_labels)}]" if cfg.watch_labels else ""
        )
        return True, f"Jira: Connected\n  - {email} ({domain}){label_info}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class JiraClient(BasePlatformClient):
    spec = JIRA
    PLATFORM_ID = JIRA.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[JiraCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._last_poll_time: Optional[str] = None
        self._seen_issue_keys: set = set()
        self._catchup_done: bool = False

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> JiraCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, JiraCredential)
        if self._cred is None:
            raise RuntimeError("No Jira credentials. Use /jira login first.")
        return self._cred

    def _is_oauth(self) -> bool:
        cred = self._load()
        return bool(cred.cloud_id and cred.access_token)

    def _base_url(self) -> str:
        cred = self._load()
        if cred.cloud_id:
            return f"{JIRA_CLOUD_API}/{cred.cloud_id}/rest/api/3"
        if cred.domain:
            domain = cred.domain.rstrip("/")
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            return f"{domain}/rest/api/3"
        raise RuntimeError("No Jira domain or cloud_id configured.")

    def _agile_base_url(self) -> str:
        cred = self._load()
        if cred.cloud_id:
            return f"{JIRA_CLOUD_API}/{cred.cloud_id}/rest/agile/1.0"
        if cred.domain:
            domain = cred.domain.rstrip("/")
            if not domain.startswith("http"):
                domain = f"https://{domain}"
            return f"{domain}/rest/agile/1.0"
        raise RuntimeError("No Jira domain or cloud_id configured.")

    def _headers(self) -> Dict[str, str]:
        cred = self._load()
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if cred.cloud_id and cred.access_token:
            headers["Authorization"] = f"Bearer {cred.access_token}"
        elif cred.email and cred.api_token:
            raw = f"{cred.email}:{cred.api_token}"
            headers["Authorization"] = (
                f"Basic {base64.b64encode(raw.encode()).decode()}"
            )
        else:
            raise RuntimeError("Incomplete Jira credentials.")
        return headers

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return await self.add_comment(recipient, text)

    # ----- Watch labels / tag (read from jira_config.json) -----

    def _config(self) -> JiraConfig:
        return load_config(_jira_config_file(), JiraConfig) or JiraConfig()

    def get_watch_labels(self) -> List[str]:
        return list(self._config().watch_labels)

    def set_watch_labels(self, labels: List[str]) -> None:
        cfg = self._config()
        cfg.watch_labels = [lbl.strip() for lbl in labels if lbl.strip()]
        save_config(_jira_config_file(), cfg)
        logger.info(f"[JIRA] Watch labels set to: {cfg.watch_labels or '(all issues)'}")

    def add_watch_label(self, label: str) -> None:
        cfg = self._config()
        label = label.strip()
        if label and label not in cfg.watch_labels:
            cfg.watch_labels.append(label)
            save_config(_jira_config_file(), cfg)

    def remove_watch_label(self, label: str) -> None:
        cfg = self._config()
        label = label.strip()
        if label in cfg.watch_labels:
            cfg.watch_labels.remove(label)
            save_config(_jira_config_file(), cfg)

    def get_watch_tag(self) -> str:
        return self._config().watch_tag

    def set_watch_tag(self, tag: str) -> None:
        cfg = self._config()
        cfg.watch_tag = tag.strip()
        save_config(_jira_config_file(), cfg)

    # ----- Listening -----

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return
        self._message_callback = callback
        self._load()

        me = await self.get_myself()
        if "error" in me:
            raise RuntimeError(f"Invalid Jira credentials: {me.get('error')}")
        display = me.get("result", {}).get("displayName", "unknown")
        logger.info(f"[JIRA] Authenticated as: {display}")

        self._last_poll_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        self._catchup_done = True
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
        while self._listening:
            try:
                await self._check_updates()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[JIRA] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_updates(self) -> None:
        if not self._last_poll_time:
            return

        self._load()  # ensure credentials are loaded; required by _base_url()/_headers()
        cfg = self._config()
        jql_parts = [f'updated >= "{self._last_poll_time}"']
        if cfg.watch_labels:
            label_clauses = " OR ".join(f'labels = "{lbl}"' for lbl in cfg.watch_labels)
            jql_parts.append(f"({label_clauses})")
        jql = " AND ".join(jql_parts) + " ORDER BY updated ASC"

        result = await arequest(
            "POST",
            f"{self._base_url()}/search/jql",
            headers=self._headers(),
            json={
                "jql": jql,
                "maxResults": 50,
                "fields": [
                    "summary",
                    "status",
                    "assignee",
                    "reporter",
                    "labels",
                    "updated",
                    "comment",
                    "issuetype",
                    "priority",
                    "project",
                ],
            },
            timeout=30.0,
            expected=(200,),
        )
        if "error" in result:
            if "401" in result["error"]:
                logger.warning("[JIRA] Authentication expired (401)")
            else:
                logger.warning(f"[JIRA] Search API {result['error']}")
            return

        for issue in (result["result"] or {}).get("issues", []):
            issue_key = issue.get("key", "")
            updated = issue.get("fields", {}).get("updated", "")
            dedup_key = f"{issue_key}:{updated}"
            if dedup_key in self._seen_issue_keys:
                continue
            self._seen_issue_keys.add(dedup_key)
            await self._dispatch_issue(issue)

        self._last_poll_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        if len(self._seen_issue_keys) > 500:
            self._seen_issue_keys = set(list(self._seen_issue_keys)[-200:])

    async def _dispatch_issue(self, issue: Dict[str, Any]) -> None:
        if not self._message_callback:
            return

        cfg = self._config()
        fields_data = issue.get("fields", {})
        issue_key = issue.get("key", "")
        summary = fields_data.get("summary", "")
        status_name = (fields_data.get("status") or {}).get("name", "")
        issue_type = (fields_data.get("issuetype") or {}).get("name", "")
        priority = (fields_data.get("priority") or {}).get("name", "")
        project_key = (fields_data.get("project") or {}).get("key", "")
        labels = fields_data.get("labels", [])

        assignee = fields_data.get("assignee") or {}
        assignee_name = assignee.get("displayName", "Unassigned")
        reporter = fields_data.get("reporter") or {}
        reporter_name = reporter.get("displayName", "Unknown")
        comments = (fields_data.get("comment") or {}).get("comments", [])

        watch_tag = cfg.watch_tag
        if watch_tag:
            matching_comment = None
            tag_lower = watch_tag.lower()
            for comment in reversed(comments):
                comment_body = _extract_adf_text(comment.get("body", {}))
                if tag_lower in comment_body.lower():
                    comment_id = comment.get("id", "")
                    comment_dedup = f"{issue_key}:comment:{comment_id}"
                    if comment_dedup in self._seen_issue_keys:
                        continue
                    self._seen_issue_keys.add(comment_dedup)
                    matching_comment = comment
                    break

            if matching_comment is None:
                return

            comment_author = (matching_comment.get("author") or {}).get(
                "displayName", "Unknown"
            )
            comment_author_id = (matching_comment.get("author") or {}).get(
                "accountId", ""
            )
            comment_body = _extract_adf_text(matching_comment.get("body", {}))
            idx = comment_body.lower().find(tag_lower)
            instruction = (
                comment_body[idx + len(watch_tag) :].strip()
                if idx >= 0
                else comment_body
            )

            text_parts = [
                f"[{issue_key}] {summary}",
                f"Status: {status_name} | Assignee: {assignee_name}",
                f"Comment by {comment_author}: {instruction or comment_body}",
            ]

            timestamp = None
            try:
                timestamp = datetime.fromisoformat(
                    matching_comment.get("created", "").replace("Z", "+00:00")
                )
            except Exception:
                pass

            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=comment_author_id,
                    sender_name=comment_author,
                    text="\n".join(text_parts),
                    channel_id=project_key,
                    channel_name=f"{project_key} ({issue_type})",
                    message_id=f"{issue_key}:{matching_comment.get('id', '')}",
                    timestamp=timestamp,
                    raw={
                        "issue": issue,
                        "trigger": "comment_tag",
                        "tag": watch_tag,
                        "instruction": instruction or comment_body,
                        "comment": matching_comment,
                    },
                )
            )
            return

        text_parts = [
            f"[{issue_key}] {summary}",
            f"Type: {issue_type} | Priority: {priority} | Status: {status_name}",
            f"Project: {project_key} | Assignee: {assignee_name}",
        ]
        if labels:
            text_parts.append(f"Labels: {', '.join(labels)}")
        if comments:
            latest = comments[-1]
            cb = _extract_adf_text(latest.get("body", {}))
            ca = (latest.get("author") or {}).get("displayName", "")
            if cb:
                text_parts.append(f"Latest comment by {ca}: {cb[:200]}")

        timestamp = None
        try:
            timestamp = datetime.fromisoformat(
                fields_data.get("updated", "").replace("Z", "+00:00")
            )
        except Exception:
            pass

        await self._message_callback(
            PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=reporter.get("accountId", ""),
                sender_name=reporter_name,
                text="\n".join(text_parts),
                channel_id=project_key,
                channel_name=f"{project_key} ({issue_type})",
                message_id=issue_key,
                timestamp=timestamp,
                raw=issue,
            )
        )

    # ----- REST API -----

    async def get_myself(self) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/myself",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "accountId": d.get("accountId"),
                "displayName": d.get("displayName"),
                "emailAddress": d.get("emailAddress", ""),
                "active": d.get("active", True),
            },
        )

    async def search_issues(
        self, jql: str, max_results: int = 50, fields_list: Optional[List[str]] = None
    ) -> Result:
        payload: Dict[str, Any] = {"jql": jql, "maxResults": min(max_results, 100)}
        if fields_list:
            payload["fields"] = fields_list
        return await arequest(
            "POST",
            f"{self._base_url()}/search/jql",
            headers=self._headers(),
            json=payload,
            timeout=30.0,
            expected=(200,),
            transform=lambda d: {
                "total": d.get("total", 0),
                "issues": d.get("issues", []),
            },
        )

    async def get_issue(
        self, issue_key: str, fields_list: Optional[List[str]] = None
    ) -> Result:
        params: Dict[str, Any] = {}
        if fields_list:
            params["fields"] = ",".join(fields_list)
        return await arequest(
            "GET",
            f"{self._base_url()}/issue/{issue_key}",
            headers=self._headers(),
            params=params,
            expected=(200,),
        )

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: Optional[str] = None,
        assignee_id: Optional[str] = None,
        labels: Optional[List[str]] = None,
        priority: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Result:
        fields_payload: Dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields_payload["description"] = _text_to_adf(description)
        if assignee_id:
            fields_payload["assignee"] = {"accountId": assignee_id}
        if labels:
            fields_payload["labels"] = labels
        if priority:
            fields_payload["priority"] = {"name": priority}
        if extra_fields:
            fields_payload.update(extra_fields)

        return await arequest(
            "POST",
            f"{self._base_url()}/issue",
            headers=self._headers(),
            json={"fields": fields_payload},
            transform=lambda d: {
                "id": d.get("id"),
                "key": d.get("key"),
                "self": d.get("self"),
            },
        )

    async def update_issue(
        self, issue_key: str, fields_update: Dict[str, Any]
    ) -> Result:
        return await arequest(
            "PUT",
            f"{self._base_url()}/issue/{issue_key}",
            headers=self._headers(),
            json={"fields": fields_update},
            expected=(204,),
            transform=lambda _d: {"updated": True, "key": issue_key},
        )

    async def add_comment(self, issue_key: str, body: str) -> Result:
        return await arequest(
            "POST",
            f"{self._base_url()}/issue/{issue_key}/comment",
            headers=self._headers(),
            json={"body": _text_to_adf(body)},
            transform=lambda d: {
                "id": d.get("id"),
                "created": d.get("created"),
                "author": (d.get("author") or {}).get("displayName", ""),
            },
        )

    async def get_transitions(self, issue_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issue/{issue_key}/transitions",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "transitions": [
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "to": (t.get("to") or {}).get("name", ""),
                    }
                    for t in d.get("transitions", [])
                ]
            },
        )

    async def transition_issue(
        self, issue_key: str, transition_id: str, comment: Optional[str] = None
    ) -> Result:
        payload: Dict[str, Any] = {"transition": {"id": transition_id}}
        if comment:
            payload["update"] = {"comment": [{"add": {"body": _text_to_adf(comment)}}]}
        return await arequest(
            "POST",
            f"{self._base_url()}/issue/{issue_key}/transitions",
            headers=self._headers(),
            json=payload,
            expected=(204,),
            transform=lambda _d: {"transitioned": True, "key": issue_key},
        )

    async def assign_issue(
        self, issue_key: str, account_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "PUT",
            f"{self._base_url()}/issue/{issue_key}/assignee",
            headers=self._headers(),
            json={"accountId": account_id},
            expected=(204,),
            transform=lambda _d: {"assigned": True, "key": issue_key},
        )

    async def get_projects(self, max_results: int = 50) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/project/search",
            headers=self._headers(),
            params={"maxResults": max_results},
            expected=(200,),
            transform=lambda d: {
                "projects": [
                    {
                        "id": p.get("id"),
                        "key": p.get("key"),
                        "name": p.get("name"),
                        "style": p.get("style", ""),
                    }
                    for p in d.get("values", [])
                ]
            },
        )

    async def search_users(self, query: str, max_results: int = 20) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/user/search",
            headers=self._headers(),
            params={"query": query, "maxResults": max_results},
            expected=(200,),
            transform=lambda d: {
                "users": [
                    {
                        "accountId": u.get("accountId"),
                        "displayName": u.get("displayName"),
                        "emailAddress": u.get("emailAddress", ""),
                        "active": u.get("active", True),
                    }
                    for u in d
                ]
            },
        )

    async def get_issue_comments(self, issue_key: str, max_results: int = 50) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issue/{issue_key}/comment",
            headers=self._headers(),
            params={"maxResults": max_results, "orderBy": "-created"},
            expected=(200,),
            transform=lambda d: {
                "comments": [
                    {
                        "id": c.get("id"),
                        "author": (c.get("author") or {}).get("displayName", ""),
                        "body": _extract_adf_text(c.get("body", {})),
                        "created": c.get("created"),
                        "updated": c.get("updated"),
                    }
                    for c in d.get("comments", [])
                ],
                "total": d.get("total", 0),
            },
        )

    async def get_statuses(self, project_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/project/{project_key}/statuses",
            headers=self._headers(),
            expected=(200,),
        )

    async def add_labels(self, issue_key: str, labels: List[str]) -> Result:
        return await arequest(
            "PUT",
            f"{self._base_url()}/issue/{issue_key}",
            headers=self._headers(),
            json={"update": {"labels": [{"add": label} for label in labels]}},
            expected=(204,),
            transform=lambda _d: {"labels_added": labels, "key": issue_key},
        )

    async def remove_labels(self, issue_key: str, labels: List[str]) -> Result:
        return await arequest(
            "PUT",
            f"{self._base_url()}/issue/{issue_key}",
            headers=self._headers(),
            json={"update": {"labels": [{"remove": label} for label in labels]}},
            expected=(204,),
            transform=lambda _d: {"labels_removed": labels, "key": issue_key},
        )

    # ----- Issue: delete -----

    async def delete_issue(
        self, issue_key: str, delete_subtasks: bool = False
    ) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/issue/{issue_key}",
            headers=self._headers(),
            params={"deleteSubtasks": "true" if delete_subtasks else "false"},
            expected=(204,),
            transform=lambda _d: {"deleted": True, "key": issue_key},
        )

    # ----- Comments: edit / delete -----

    async def update_comment(
        self, issue_key: str, comment_id: str, body: str
    ) -> Result:
        return await arequest(
            "PUT",
            f"{self._base_url()}/issue/{issue_key}/comment/{comment_id}",
            headers=self._headers(),
            json={"body": _text_to_adf(body)},
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "updated": d.get("updated"),
                "author": (d.get("author") or {}).get("displayName", ""),
            },
        )

    async def delete_comment(self, issue_key: str, comment_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/issue/{issue_key}/comment/{comment_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "comment_id": comment_id},
        )

    # ----- Watchers -----

    async def get_watchers(self, issue_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issue/{issue_key}/watchers",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "is_watching": d.get("isWatching", False),
                "watch_count": d.get("watchCount", 0),
                "watchers": [
                    {
                        "accountId": w.get("accountId"),
                        "displayName": w.get("displayName"),
                        "active": w.get("active", True),
                    }
                    for w in d.get("watchers", [])
                ],
            },
        )

    async def add_watcher(self, issue_key: str, account_id: str) -> Result:
        # API requires accountId sent as JSON string literal (quoted)
        headers = self._headers()
        return await arequest(
            "POST",
            f"{self._base_url()}/issue/{issue_key}/watchers",
            headers=headers,
            json=account_id,
            expected=(204,),
            transform=lambda _d: {"added": True, "account_id": account_id},
        )

    async def remove_watcher(self, issue_key: str, account_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/issue/{issue_key}/watchers",
            headers=self._headers(),
            params={"accountId": account_id},
            expected=(204,),
            transform=lambda _d: {"removed": True, "account_id": account_id},
        )

    # ----- Attachments -----

    async def add_attachment(
        self, issue_key: str, file_path: str, filename: Optional[str] = None
    ) -> Result:
        """Upload a file as an attachment. Uses multipart form; sets X-Atlassian-Token: no-check."""
        cred = self._load()
        # Build headers without Content-Type so httpx sets multipart boundary
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "X-Atlassian-Token": "no-check",
        }
        if cred.cloud_id and cred.access_token:
            headers["Authorization"] = f"Bearer {cred.access_token}"
        elif cred.email and cred.api_token:
            raw = f"{cred.email}:{cred.api_token}"
            headers["Authorization"] = (
                f"Basic {base64.b64encode(raw.encode()).decode()}"
            )
        else:
            raise RuntimeError("Incomplete Jira credentials.")

        try:
            with open(file_path, "rb") as fh:
                file_bytes = fh.read()
        except OSError as e:
            return {"error": "file_read_failed", "details": str(e)}

        import os

        name = filename or os.path.basename(file_path)

        return await arequest(
            "POST",
            f"{self._base_url()}/issue/{issue_key}/attachments",
            headers=headers,
            files={"file": (name, file_bytes)},
            expected=(200,),
            transform=lambda d: {
                "attachments": [
                    {
                        "id": a.get("id"),
                        "filename": a.get("filename"),
                        "size": a.get("size"),
                        "content": a.get("content"),
                    }
                    for a in (d if isinstance(d, list) else [])
                ]
            },
        )

    async def get_attachment(self, attachment_id: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/attachment/{attachment_id}",
            headers=self._headers(),
            expected=(200,),
        )

    async def delete_attachment(self, attachment_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/attachment/{attachment_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "attachment_id": attachment_id},
        )

    async def download_attachment(self, attachment_id: str, dest_path: str) -> Result:
        """Resolve the attachment's content URL and stream bytes to ``dest_path``."""
        meta = await self.get_attachment(attachment_id)
        if "error" in meta:
            return meta
        content_url = (meta.get("result") or {}).get("content")
        if not content_url:
            return {"error": "no_content_url"}
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                async with client.stream(
                    "GET", content_url, headers=self._headers()
                ) as r:
                    if r.status_code != 200:
                        return {"error": f"http_{r.status_code}"}
                    with open(dest_path, "wb") as fh:
                        async for chunk in r.aiter_bytes():
                            fh.write(chunk)
            return {
                "ok": True,
                "result": {"saved_to": dest_path, "attachment_id": attachment_id},
            }
        except Exception as e:
            return {"error": "download_failed", "details": str(e)}

    # ----- Worklogs -----

    async def add_worklog(
        self,
        issue_key: str,
        time_spent: Optional[str] = None,
        time_spent_seconds: Optional[int] = None,
        comment: Optional[str] = None,
        started: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if time_spent:
            payload["timeSpent"] = time_spent
        if time_spent_seconds is not None:
            payload["timeSpentSeconds"] = time_spent_seconds
        if comment:
            payload["comment"] = _text_to_adf(comment)
        if started:
            payload["started"] = started
        return await arequest(
            "POST",
            f"{self._base_url()}/issue/{issue_key}/worklog",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda d: {
                "id": d.get("id"),
                "timeSpent": d.get("timeSpent"),
                "timeSpentSeconds": d.get("timeSpentSeconds"),
                "started": d.get("started"),
                "author": (d.get("author") or {}).get("displayName", ""),
            },
        )

    async def get_worklogs(self, issue_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issue/{issue_key}/worklog",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "worklogs": [
                    {
                        "id": w.get("id"),
                        "timeSpent": w.get("timeSpent"),
                        "timeSpentSeconds": w.get("timeSpentSeconds"),
                        "started": w.get("started"),
                        "author": (w.get("author") or {}).get("displayName", ""),
                        "comment": _extract_adf_text(w.get("comment", {})),
                    }
                    for w in d.get("worklogs", [])
                ],
                "total": d.get("total", 0),
            },
        )

    async def update_worklog(
        self,
        issue_key: str,
        worklog_id: str,
        time_spent: Optional[str] = None,
        time_spent_seconds: Optional[int] = None,
        comment: Optional[str] = None,
        started: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if time_spent:
            payload["timeSpent"] = time_spent
        if time_spent_seconds is not None:
            payload["timeSpentSeconds"] = time_spent_seconds
        if comment:
            payload["comment"] = _text_to_adf(comment)
        if started:
            payload["started"] = started
        return await arequest(
            "PUT",
            f"{self._base_url()}/issue/{issue_key}/worklog/{worklog_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "timeSpent": d.get("timeSpent"),
                "updated": d.get("updated"),
            },
        )

    async def delete_worklog(self, issue_key: str, worklog_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/issue/{issue_key}/worklog/{worklog_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "worklog_id": worklog_id},
        )

    # ----- Issue links -----

    async def create_issue_link(
        self,
        link_type: str,
        inward_issue_key: str,
        outward_issue_key: str,
        comment: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_issue_key},
            "outwardIssue": {"key": outward_issue_key},
        }
        if comment:
            payload["comment"] = {"body": _text_to_adf(comment)}
        return await arequest(
            "POST",
            f"{self._base_url()}/issueLink",
            headers=self._headers(),
            json=payload,
            expected=(201,),
            transform=lambda _d: {
                "created": True,
                "type": link_type,
                "inward": inward_issue_key,
                "outward": outward_issue_key,
            },
        )

    async def get_issue_link(self, link_id: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issueLink/{link_id}",
            headers=self._headers(),
            expected=(200,),
        )

    async def delete_issue_link(self, link_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/issueLink/{link_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "link_id": link_id},
        )

    async def list_issue_link_types(self) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issueLinkType",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "types": [
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "inward": t.get("inward"),
                        "outward": t.get("outward"),
                    }
                    for t in d.get("issueLinkTypes", [])
                ]
            },
        )

    # ----- Versions -----

    async def list_versions(self, project_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/project/{project_key}/versions",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "versions": [
                    {
                        "id": v.get("id"),
                        "name": v.get("name"),
                        "released": v.get("released"),
                        "archived": v.get("archived"),
                        "releaseDate": v.get("releaseDate"),
                    }
                    for v in (d if isinstance(d, list) else [])
                ]
            },
        )

    async def create_version(
        self,
        project_key: str,
        name: str,
        description: Optional[str] = None,
        release_date: Optional[str] = None,
        start_date: Optional[str] = None,
        released: bool = False,
    ) -> Result:
        # /version requires projectId (not key). Resolve project first.
        proj = await self.get_project(project_key)
        if "error" in proj:
            return proj
        project_id = (proj.get("result") or {}).get("id") or (
            proj.get("result") or {}
        ).get("projectId")
        if not project_id:
            return {"error": "project_id_not_found"}
        payload: Dict[str, Any] = {
            "name": name,
            "projectId": int(project_id),
            "released": released,
        }
        if description:
            payload["description"] = description
        if release_date:
            payload["releaseDate"] = release_date
        if start_date:
            payload["startDate"] = start_date
        return await arequest(
            "POST",
            f"{self._base_url()}/version",
            headers=self._headers(),
            json=payload,
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("name"),
                "released": d.get("released"),
            },
        )

    async def update_version(
        self,
        version_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        release_date: Optional[str] = None,
        released: Optional[bool] = None,
        archived: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if release_date is not None:
            payload["releaseDate"] = release_date
        if released is not None:
            payload["released"] = released
        if archived is not None:
            payload["archived"] = archived
        return await arequest(
            "PUT",
            f"{self._base_url()}/version/{version_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    async def delete_version(self, version_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/version/{version_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "version_id": version_id},
        )

    # ----- Components -----

    async def list_components(self, project_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/project/{project_key}/components",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "components": [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "description": c.get("description", ""),
                        "lead": (c.get("lead") or {}).get("displayName", ""),
                    }
                    for c in (d if isinstance(d, list) else [])
                ]
            },
        )

    async def create_component(
        self,
        project_key: str,
        name: str,
        description: Optional[str] = None,
        lead_account_id: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"project": project_key, "name": name}
        if description:
            payload["description"] = description
        if lead_account_id:
            payload["leadAccountId"] = lead_account_id
        return await arequest(
            "POST",
            f"{self._base_url()}/component",
            headers=self._headers(),
            json=payload,
            transform=lambda d: {"id": d.get("id"), "name": d.get("name")},
        )

    async def delete_component(self, component_id: str) -> Result:
        return await arequest(
            "DELETE",
            f"{self._base_url()}/component/{component_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "component_id": component_id},
        )

    # ----- Project / metadata lookups -----

    async def get_project(self, project_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/project/{project_key}",
            headers=self._headers(),
            expected=(200,),
        )

    async def list_priorities(self) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/priority",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "priorities": [
                    {"id": p.get("id"), "name": p.get("name")}
                    for p in (d if isinstance(d, list) else [])
                ]
            },
        )

    async def list_issue_types(self) -> Result:
        return await arequest(
            "GET",
            f"{self._base_url()}/issuetype",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: {
                "issue_types": [
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                    }
                    for t in (d if isinstance(d, list) else [])
                ]
            },
        )

    # ----- Agile: boards -----

    async def list_boards(
        self,
        project_key: Optional[str] = None,
        board_type: Optional[str] = None,
        max_results: int = 50,
    ) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if project_key:
            params["projectKeyOrId"] = project_key
        if board_type:
            params["type"] = board_type
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/board",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "boards": [
                    {
                        "id": b.get("id"),
                        "name": b.get("name"),
                        "type": b.get("type"),
                        "location": (b.get("location") or {}).get("projectKey", ""),
                    }
                    for b in d.get("values", [])
                ],
                "total": d.get("total", 0),
            },
        )

    async def get_board(self, board_id: int) -> Result:
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/board/{board_id}",
            headers=self._headers(),
            expected=(200,),
        )

    async def get_board_issues(
        self, board_id: int, jql: Optional[str] = None, max_results: int = 50
    ) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if jql:
            params["jql"] = jql
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/board/{board_id}/issue",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "issues": d.get("issues", []),
                "total": d.get("total", 0),
            },
        )

    async def get_board_sprints(
        self, board_id: int, state: Optional[str] = None, max_results: int = 50
    ) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if state:
            params["state"] = state
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/board/{board_id}/sprint",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "sprints": [
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "state": s.get("state"),
                        "startDate": s.get("startDate"),
                        "endDate": s.get("endDate"),
                        "goal": s.get("goal", ""),
                    }
                    for s in d.get("values", [])
                ],
                "total": d.get("total", 0),
            },
        )

    async def get_board_backlog(self, board_id: int, max_results: int = 50) -> Result:
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/board/{board_id}/backlog",
            headers=self._headers(),
            params={"maxResults": max_results},
            expected=(200,),
            transform=lambda d: {
                "issues": d.get("issues", []),
                "total": d.get("total", 0),
            },
        )

    # ----- Agile: sprints -----

    async def get_sprint(self, sprint_id: int) -> Result:
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/sprint/{sprint_id}",
            headers=self._headers(),
            expected=(200,),
        )

    async def get_sprint_issues(
        self, sprint_id: int, jql: Optional[str] = None, max_results: int = 50
    ) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if jql:
            params["jql"] = jql
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/sprint/{sprint_id}/issue",
            headers=self._headers(),
            params=params,
            expected=(200,),
            transform=lambda d: {
                "issues": d.get("issues", []),
                "total": d.get("total", 0),
            },
        )

    async def create_sprint(
        self,
        name: str,
        board_id: int,
        goal: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"name": name, "originBoardId": board_id}
        if goal:
            payload["goal"] = goal
        if start_date:
            payload["startDate"] = start_date
        if end_date:
            payload["endDate"] = end_date
        return await arequest(
            "POST",
            f"{self._agile_base_url()}/sprint",
            headers=self._headers(),
            json=payload,
            transform=lambda d: {
                "id": d.get("id"),
                "name": d.get("name"),
                "state": d.get("state"),
            },
        )

    async def update_sprint(
        self,
        sprint_id: int,
        name: Optional[str] = None,
        state: Optional[str] = None,
        goal: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if state is not None:
            payload["state"] = state
        if goal is not None:
            payload["goal"] = goal
        if start_date is not None:
            payload["startDate"] = start_date
        if end_date is not None:
            payload["endDate"] = end_date
        return await arequest(
            "POST",
            f"{self._agile_base_url()}/sprint/{sprint_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    async def delete_sprint(self, sprint_id: int) -> Result:
        return await arequest(
            "DELETE",
            f"{self._agile_base_url()}/sprint/{sprint_id}",
            headers=self._headers(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "sprint_id": sprint_id},
        )

    async def move_issues_to_sprint(
        self, sprint_id: int, issue_keys: List[str]
    ) -> Result:
        return await arequest(
            "POST",
            f"{self._agile_base_url()}/sprint/{sprint_id}/issue",
            headers=self._headers(),
            json={"issues": issue_keys},
            expected=(204,),
            transform=lambda _d: {
                "moved": True,
                "sprint_id": sprint_id,
                "issues": issue_keys,
            },
        )

    async def move_issues_to_backlog(self, issue_keys: List[str]) -> Result:
        return await arequest(
            "POST",
            f"{self._agile_base_url()}/backlog/issue",
            headers=self._headers(),
            json={"issues": issue_keys},
            expected=(204,),
            transform=lambda _d: {"moved": True, "issues": issue_keys},
        )

    # ----- Agile: epics -----

    async def get_epic(self, epic_id_or_key: str) -> Result:
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/epic/{epic_id_or_key}",
            headers=self._headers(),
            expected=(200,),
        )

    async def get_epic_issues(
        self, epic_id_or_key: str, max_results: int = 50
    ) -> Result:
        return await arequest(
            "GET",
            f"{self._agile_base_url()}/epic/{epic_id_or_key}/issue",
            headers=self._headers(),
            params={"maxResults": max_results},
            expected=(200,),
            transform=lambda d: {
                "issues": d.get("issues", []),
                "total": d.get("total", 0),
            },
        )

    async def move_issues_to_epic(
        self, epic_id_or_key: str, issue_keys: List[str]
    ) -> Result:
        return await arequest(
            "POST",
            f"{self._agile_base_url()}/epic/{epic_id_or_key}/issue",
            headers=self._headers(),
            json={"issues": issue_keys},
            expected=(204,),
            transform=lambda _d: {
                "moved": True,
                "epic": epic_id_or_key,
                "issues": issue_keys,
            },
        )


# -----------------------------------------------------------------
# ADF helpers
# -----------------------------------------------------------------


def _text_to_adf(text: str) -> Dict[str, Any]:
    paragraphs = text.split("\n")
    content = []
    for para in paragraphs:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": para}] if para else [],
            }
        )
    return {"version": 1, "type": "doc", "content": content}


def _extract_adf_text(adf: Dict[str, Any]) -> str:
    if not isinstance(adf, dict):
        return str(adf) if adf else ""
    parts: List[str] = []

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(adf)
    return " ".join(parts)
